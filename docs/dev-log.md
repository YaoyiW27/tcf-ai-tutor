# Dev Log

## 2026-08-16

### Scoring-reference RAG — slice 1: gateway embeddings endpoint
- Kicked off the deferred **pgvector RAG** workload item (ground grading in CEFR/TCF rubric
  descriptors). Design settled with the user: corpus = **hand-authored CEFR/TCF band descriptors**
  (copyright-clean; exemplar-based RAG deferred), retrieval injected into the **score node**, and
  embeddings go **through the gateway** so they're metered/observable like chat.
- **This slice = the gateway `POST /v1/embeddings` passthrough only** (no DB / retrieval yet).
  Always routed to **OpenAI** (`text-embedding-3-small`) regardless of `INFERENCE_BACKEND` —
  Anthropic has no embeddings API, so the chat backend can stay `anthropic`/`vllm` while embeddings
  stay on OpenAI. New config `OPENAI_API_KEY` / `OPENAI_BASE_URL` (independent of the forward-path
  `UPSTREAM_*`). Request/response pass through verbatim; only usage is read for metrics.
- **Own metric family** (`gateway_embedding_{requests_total,latency_seconds,tokens_input_total,cost_usd_total}`,
  labelled by `model` only — no `backend`, embeddings are always OpenAI) kept separate from the chat
  counters so the chat dashboards and the **inflight-based HPA signal stay chat-only** (embeddings
  deliberately don't touch `gateway_inflight_requests`). Cost table gained `text-embedding-3-{small,large}`
  (input-only pricing). Rate-limited on the same per-key bucket; 429/503/502 mapped like chat.
- Tests (`gateway/tests/test_embeddings.py`, mocked httpx — no network): forward URL/key/body,
  usage read-out, missing-key → RuntimeError, independence from `inference_backend`, endpoint
  success metrics, 503/502/429 mapping, and the embedding metric-family type/label contract.
  Gateway suite **35 passed** (was 24).
- Next RAG slices: (2) pgvector table + Alembic migration (needs `pgvector/pgvector:pg16` image in
  compose/K8s) + rubric-descriptor loader; (3) retrieval into `score_essay` (writing + speaking).

### Scoring-reference RAG — slice 2: pgvector storage + rubric corpus + loader
- **pgvector schema.** New `rubric_chunks` model (`app/models.py`): `(exam_section, cefr_level,
  dimension, text, source, embedding vector(1536))`, unique on
  `(exam_section, dimension, cefr_level, source)`. Reuses the existing `exam_section` /
  `difficulty_level` enums. Migration `a1b2c3d4e5f6` enables the `vector` extension and creates the
  table; the enums are referenced with `create_type=False` (they already exist) and are **not**
  dropped on downgrade (shared with other tables); no ANN index (~12-row corpus → exact `<->` scan).
  Added `pgvector==0.3.6`; switched the compose + K8s Postgres image to **`pgvector/pgvector:pg16`**
  (drop-in, no official alpine tag). `embedding_model`/`embedding_dimensions` added to backend config.
- **Corpus** (`app/rubric_corpus.py`): 12 hand-authored, copyright-clean CEFR band descriptors — one
  holistic descriptor per `(writing|speaking) × A1..C2`, in English (they ground the English grader
  prompt). Speaking descriptors note pronunciation is out of scope (transcript-only), matching the
  speaking grader. `dimension="overall"` for now; the column leaves room for per-dimension chunks.
- **Embedding helper** (`app/embeddings.py`): `embed_texts`/`embed_text` go through the gateway
  `/v1/embeddings` (slice 1) — same chokepoint the graders use — so embeddings are metered/observable
  and the backend holds no provider key. Response is re-sorted by `index` so order never depends on
  the upstream. **Loader** (`scripts.seed_rubrics`, idempotent, keyed on the unique tuple) is **not**
  in the backend entrypoint (unlike `seed_questions`) because it needs the gateway up — run manually.
- **Verified the migration live** against a throwaway `pgvector/pgvector:pg16` container: `upgrade head`
  built `rubric_chunks` with `embedding vector(1536)` + the unique constraint + the `vector`
  extension; `downgrade -1` dropped the table but kept the shared enums; re-`upgrade` round-tripped.
- Tests (mocked, no DB/gateway): `test_rubric_corpus.py` (section×level coverage, unique keys,
  substantive text, `rubric_key` enum/string stability, `filter_new` skip-existing) +
  `test_embeddings.py` (batch ordering by `index`, empty short-circuit, single-vector wrapper,
  count mismatch). Backend suite **23 passed** (was 12).
- Next: slice 3 — embed the essay/transcript as a query, retrieve top-k, inject into `score_essay`
  (writing + speaking); grading must still work when the table is empty (RAG is additive).

## 2026-08-14 (Part B follow-up — fallback correctness + doc accuracy)

Two accuracy fixes after reviewing Part B (no new features):
- **Gateway `guided_json` fallback was too eager.** `_forward_backend` retried on *any* 400 carrying a
  json_schema, not only a "response_format unsupported" 400. During the live run, before
  `--max-model-len` was raised, every grader call 400'd on context length — and every one carried a
  json_schema, so each was silently sent **twice** (double spend on a metered GPU), and
  `raise_for_status()` surfaced the *second* (guided_json-rewritten) response, masking the real
  max-model-len cause. Fix: retry only when the 400 body names `response_format`
  (`_is_response_format_error`); memoize the verdict per upstream (`_rejects_response_format`) so a
  genuinely-old vLLM costs **one probe**, not a retry per request. `upstream_seconds` is now re-timed on
  the retry (the returned call), not the probe+retry sum — the old sum inflated upstream time and
  understated `gateway_overhead_seconds` (the signature A/B metric). Tests (`test_forward_fallback.py`,
  now 4): a non-`response_format` 400 must **not** retry (+ nothing memoized), and the reject verdict is
  cached so it probes once. Extended `mock_upstream.py` with a context-length reject mode. Gateway suite
  **24 passed**.
- **Runbook §5 / dev-log claims tightened to match what was actually measured:** corrected "the
  `guided_json` fallback never fired" (it did, on every max-model-len 400); named the eval model
  (**FP16**, before the AWQ redeploy) and framed `eval_grader 3/3` as a *pipeline* check (3 assertions
  vs a non-deterministic model), not a grading-quality result; **the FP16-vs-AWQ quality delta was not
  measured** (AWQ eval skipped to spin the GPU down) — recorded as performance-only; added scope notes
  that `max_completion_tokens=256` but the model emitted ~28–42 tokens (measures TTFT + short decode,
  not sustained generation) and that n=100 single-run p95/p99 rest on ~5/~1 samples (indicative, not
  stable tails).

## 2026-08-14 (Part B — live vLLM on a rented GPU)

### vLLM capstone — Part B (live validation, GPU up then down)
- Rented a **RunPod** GPU running the **vLLM OpenAI template** (not raw Docker) serving
  `Qwen/Qwen2.5-7B-Instruct`, reachable via a public HTTPS proxy. Gateway wired via gitignored
  `gateway/.env` (`INFERENCE_BACKEND=vllm` + `UPSTREAM_BASE_URL`/`UPSTREAM_API_KEY`); confirmed the
  three gateway var names against `config.py` (`INFERENCE_MODEL` there is inert — it's a **backend**
  setting; the bench passes `--model` and the grader eval takes it as an env override).
- **Live blocker found + fixed (config, not code):** the grader's `_structured_call` caps completions
  at `max_tokens=8000` (tuned for Claude's 200k window; workload stays backend-agnostic), but vLLM
  counts `prompt + max_completion_tokens` against `--max-model-len`, so the runbook's **`8192` window
  400'd every grader call** (`8000 + prompt > 8192`). Root-caused by adding a temp upstream-body log to
  `_forward_backend` (reverted) — the 400 was a context-length error, not schema/`reasoning_effort`
  (both verified fine directly). Chose to **raise the window** (redeploy at `--max-model-len 16384`,
  Qwen supports 32768) over shrinking the workload cap — keeps Claude the quality backend and the
  workload identical across backends. Fixed the runbook (`8192 → 16384` + a note on why).
- **Structured output:** this vLLM (0.27.1) accepts OpenAI **`response_format` json_schema natively**
  (200). The `guided_json` fallback didn't fire on the successful runs — but the earlier
  `--max-model-len 8192` 400s each *did* trip it, because the then-current gateway retried on any
  json_schema 400 (fixed the next day — see the follow-up entry). **`eval_grader` 3/3 passed
  end-to-end against the FP16 model** through the gateway (eval ran before the AWQ redeploy; polite
  imparfait not flagged, agreement error caught, weak answer not over-scored). This is a *pipeline*
  check, not a quality measure — grading quality trails Claude as expected (verify_errors dropped a
  real `des pomme`/gender error on one probe).
- **FP16-vs-AWQ benchmark** (n=100 × concurrency 1,4,8,16, e2e via the RunPod proxy): **AWQ-4bit is a
  straight win — +15–29% QPS, −10–22% p50/p95, +20–28% tok/s, 0 errors** at every level. vLLM
  continuous batching shows as **QPS scaling ~linearly 1→16 with ~flat p50**. Saved
  `benchmarks/results/vllm-{fp16,awq}-*.json`; `compare_results.py` for the table.
- **Authoritative serving metrics** from vLLM `/metrics`: TTFT **p50=0.06 / p95=0.08 / p99=0.10s**
  (`vllm:time_to_first_token_seconds`); serving e2e p50≈1.0s ≈ client p50, so **the RunPod proxy adds
  negligible RTT** — the ~1s is real single-stream decode (~38 tok/s), not network. Stood up the
  observability stack pointed at the RunPod `/metrics` (`scheme: https`, unauthenticated): Prometheus
  target **up**, dashboard PromQL (`histogram_quantile` over the TTFT buckets) resolved live under a
  warm-up burst, **vLLM Serving** Grafana dashboard rendered. Torn down; reverted the temp
  `prometheus.yml` target (kept the commented template, improved with an https/RunPod hint) so nothing
  ephemeral is committed. Full FP16-vs-AWQ table + observations in `docs/vllm-runbook.md §5`.
- **The GPU-dependent layer is now validated live; GPU to be spun down.** With this, the whole stack
  (gateway → observability → containers → K8s+autoscaling → Argo → vLLM serving) has run end-to-end.

## 2026-08-14 (later)

### vLLM capstone — Part A (GPU-free prep, tested)
- Decisions: self-host **Qwen2.5-7B-Instruct** on vLLM on a **raw GPU box** (user runs Docker, shares URL+key); gateway routes to it via the existing `vllm` forward path (config only, no gateway code). Scope: serving + gateway + **FP16-vs-AWQ** benchmarks + vLLM `/metrics` → Grafana; in-cluster GPU-aware HPA deferred (kind is on the Mac).
- Landed GPU-free + CI-testable: `docs/vllm-runbook.md` (vLLM launch FP16/AWQ, gateway wiring, structured-output note + `guided_json` fallback, bench + compare procedure); a **vLLM Grafana dashboard** (`infra/observability/grafana/dashboards/vllm.json`: TTFT p50/95/99, e2e latency, gen throughput, KV-cache, running/waiting) + a commented vLLM scrape job in `prometheus.yml`; `gateway/.env.example` vLLM notes. Tests: `test_vllm_dashboard_contract.py` (valid JSON + references the `vllm:*` metrics) — gateway suite 20 passed. Reuses `INFERENCE_MODEL` (Argo slice) + `bench_gateway.py --label` / `compare_results.py`.
- **Part A.2 — hardened before renting (GPU-free):** built the `response_format → guided_json` fallback **in the gateway** (`_forward_backend`: on a 400 with a json_schema response_format, retry once with vLLM's top-level `guided_json`), symmetric with `_anthropic_backend`'s `output_config` translation — the grader stays backend-agnostic (unchanged). Extended `mock_upstream.py` with a `MOCK_REJECT_RESPONSE_FORMAT` mode + `last_request` recording; added `gateway/tests/test_forward_fallback.py` (in-process via ASGITransport — asserts the fallback body carries `guided_json`/no `response_format` and still returns a completion; and no-retry when accepted). Gateway suite 22 passed; break-verify confirmed real; live HTTP smoke (gateway→reject-mode mock) returned 200 via the fallback. Fixed the runbook: client bench = **e2e latency with the network in the path** (Mac→SSH tunnel→GPU), authoritative **TTFT from `vllm:time_to_first_token_seconds`** (not the client). Confirmed AWQ id `Qwen/Qwen2.5-7B-Instruct-AWQ`; key stays in gitignored `gateway/.env` (no paste).
- **Part B (pending a live GPU):** launch vLLM, wire gateway, verify structured output + one grader eval end-to-end, run FP16-vs-AWQ benchmarks, confirm vLLM metrics in Grafana; record numbers. A 7B model's grading quality will trail Claude (expected — may trip the Argo gate).

### CI — GitHub Actions
- `.github/workflows/ci.yml` runs on push (main) + PRs: a `tests` matrix job (`gateway`, `backend`) that installs `requirements-dev.txt` and runs `pytest` per service (no DB/services — everything's mocked; backend conftest sets a dummy `DATABASE_URL`), plus an `infra-validate` job (`helm lint`/`template` the chart + `docker compose config`). Operationalizes the tests-as-DoD rule. CI badge in the README.

### Testing regime — tests are Definition of Done (project rule)
- **Rule (now in CLAUDE.md):** every slice that writes or changes code ships with tests in the
  **same** slice — a feature without a passing test isn't done; don't backfill later. Future plans
  must include that slice's tests.
- **Principles:** pytest (`gateway/tests/`, `backend/tests/`); **mock all external deps** (LLM
  APIs, DB, network) — fast, free, deterministic, **never** a real LLM call. Test our own logic
  (parsing, routing, rate-limiting, scoring, gate decisions), not model quality or third-party libs.
  Clear test names; high-value critical-path tests over coverage padding. `pyproject.toml` holds the
  pytest config so `pytest` runs the whole suite per service.
- Backfilling three key layers in review-gated steps: (1) gateway metric contract (guards the
  `/metrics` names/labels vs the Grafana PromQL), (2) gateway logic (rate limit, backend routing,
  error handling), (3) grader/eval logic (score parsing, gate decisions).

## 2026-05-19
- Initial repo, README, LICENSE, .gitignore
- Resolved divergent histories (GitHub auto-init vs local init)

## 2026-05-22
- Locked project scope: AI-native TCF tutor, learning-driven
- Added CLAUDE.md for Claude Code context
- Schema v1 design (users / questions / answers / ai_feedback)
- Architecture v1 design
- Trade-off: JSON for dimension_scores and corrections — simpler v1, migrate to normalized tables later if access patterns shift

## 2026-05-23
- Frontend foundation: Next.js 16 + shadcn/ui + Tailwind v4 + TypeScript
- Backend foundation: FastAPI on Python 3.11 (venv-based)
- Hello world page and GET /health endpoint verified end-to-end

## 2026-06-01
- Frontend ↔ Backend integration
- CORS enabled on backend (allow http://localhost:3000)
- Frontend env config: NEXT_PUBLIC_API_URL
- "Check backend" button working; renders {"status":"ok"} from backend

## 2026-06-05
- Database integration complete: PostgreSQL via SQLAlchemy (async) + Alembic
- 4 schema-v1 tables created (users, questions, answers, ai_feedback) + 3 enums, owned by tcf_app
- Alembic env.py rewritten fully async (asyncpg only); first migration is reversible (explicit enum drops in downgrade)
- Seed script (idempotent) + read-only GET /questions endpoint
- Verified end-to-end: DB → async session → FastAPI → JSON (3 TCF Writing tasks, A2/B1/B2)

## 2026-06-06
- POST /answers: stores writing submissions using a dev user via get-or-create, with status set to submitted.
- AI grader: implemented Claude structured output using messages.parse + Pydantic, with model claude-sonnet-4-6
- Scoring dimensions: task_fulfillment, coherence, vocabulary, and grammar on a 0–6 scale, plus estimated_level (CEFR), corrections, and overall_comment. estimated_level is stored inside the dimension_scores JSONB field without changing the schema.
- Added POST /answers/{id}/grade and GET /answers/{id}/feedback. Re-grading returns 409; missing API key returns 503; external API errors return 502.
- End-to-end validation passed: submit → grade → read feedback. First real AI grading output received: B2, total score 5.4.
- Known issue: the grader occasionally “corrects” French that is already correct, such as misclassifying the imparfait de politesse as an error. This will be addressed later during the LangGraph hardening phase.

## 2026-06-07
- LangGraph multi-node grading pipeline: START → score → find_errors → verify_errors → assemble → END
- 3 focused Claude calls (sonnet-4-6, serial) + pure-Python assemble; run_grader interface unchanged
- verify_errors fixes over-correction: keeps genuine errors, drops polite imparfait / stylistic rewrites; "unsure → not an error"
- Verified: previously mis-corrected "je voulais" (imparfait de politesse) now left intact; only a real error (vocative comma) flagged
- Phase 2 (Writing grader) functionally complete
- Tradeoff noted: serial calls ≈ 10-15s/grade; score+find_errors are parallelizable later if needed

## 2026-06-08
- Frontend wired to backend end-to-end: questions list + question detail page (essay submission → grade → feedback UI)
- CORS enabled (localhost:3000); client-component fetch (verifies real browser→backend path)
- Closed the loop: pick question → write → submit → AI feedback, all in the browser
- Perf: instrumented per-node timing; grading 60s → 32s (trimmed find_errors output) → 19s (parallelized score + find_errors via LangGraph fan-out/fan-in, no reducer needed — disjoint state fields)
- Scoring redesign: dropped fake 0–6-as-TCF-score; now reports estimated CEFR level + NCLC + official expression écrite band (pure-Python lookup from estimated_level, no LLM, no DB change). A1 shows "non atteint". Dimension scores relabeled "internal assessment, not official TCF points"
- Verified both ends of the band mapping (B2/NCLC7/10–11 and A1/NCLC4/non atteint)

## 2026-06-10
- Frontend: fixed repeated GET /questions on the question pages. Root cause was NOT a useEffect dependency bug — the deps were already correct (`[]` and `[id]`). It's React 19 Strict Mode double-invoking the mount effect in `next dev` (two requests ~1ms apart), compounded by Fast Refresh re-running the effect on every save. Fixed by de-duplicating the in-flight request in `lib/api.ts` (shared promise, cleared on settle) so /questions hits the backend once per page load. Verified with a mock backend + headless Chrome: a list→detail navigation dropped from 3 hits to 2 (one per load).
- Frontend UX: removed the hardcoded "10–15s" estimate (grading button + loading paragraph); kept the disabled-button + "Grading…" loading state.
- Docs: README backend run block now activates the venv before uvicorn, with a note that the prompt must show `(.venv)` or sqlalchemy won't be found.
- Observability (Phase 5 start): integrated Langfuse (4.7.1, OTEL-based). `@observe()` on `run_grader` — the LangGraph entry point only, nodes not yet instrumented — and `langfuse.flush()` after each run (finally, so it fires on success or error). Keys (LANGFUSE_PUBLIC_KEY / SECRET_KEY / HOST) read via pydantic-settings and passed explicitly to the client — same `.env`-not-`os.environ` reason as ANTHROPIC_API_KEY. Tracing disabled cleanly when keys are unset, so grading still works. Added to requirements.txt + .env.example.

## 2026-06-10

### Langfuse observability — Step 1
- Installed langfuse==4.7.1, wired to Langfuse Cloud (US region)
- Decorated top-level run_grader with @observe(), flush in finally block
- Langfuse client init is conditional: keys missing → tracing disabled silently
- First trace confirmed in dashboard: run_grader span with full input/output/latency

## 2026-06-11

### Langfuse observability — Step 2: per-node instrumentation
- Added @observe() to all four LangGraph nodes (score, find_errors, verify_errors, assemble)
- Added Langfuse generation logging with model name + token usage for score, find_errors, verify_errors
- Confirmed nested trace in dashboard: run_grader → 4 child spans, 3 with generations

### Performance discovery via Langfuse
- Langfuse revealed verify_errors_node takes ~35s when essay has errors (previously showed 0.0s because earlier test essays had no errors, so verify short-circuited)
- Root cause: adaptive thinking with no budget cap + max_tokens=8000 on a simple bool classification task
- Fix: capped thinking budget to 1024 tokens, lowered max_tokens to 2000
- Result: verify_errors 35.8s → 20.0s (~44% reduction)
- Note: total grading time varies per run due to API latency fluctuation, not code

## 2026-06-15

### Langfuse observability — Step 2 follow-up
- Fixed a tracing gap: `verify_errors` was documented as a Langfuse generation, but the code discarded its Anthropic token usage before `graph.py` could log it.
- `grader.verify_errors()` now returns `(corrections, usage)` when it calls Claude, and `([], None)` when it short-circuits because there are no candidate corrections.
- `verify_errors_node` now logs a `verify_errors` generation only when a model call actually happened, so Langfuse distinguishes "node ran with no candidates" from "node made a Claude call".
- Verified syntax with `.venv/bin/python -m compileall app`.

## 2026-06-16

### Grader regression eval v0
- Added `backend/scripts/eval_grader.py`, a small human-readable eval script for the LangGraph writing grader. It calls the real grader with fixed examples and prints PASS/FAIL, estimated CEFR/NCLC/band, and corrections.
- Covered three regression checks: polite imparfait should not be flagged (`Je voulais...`), obvious plural/agreement errors should be detected (`des pomme`, `très gentils`), and a very weak short answer should not be over-scored.
- First run passed 3/3. Runtime was roughly 50s for three real Claude-backed grading runs, reinforcing that LLM evals should stay small, targeted, and explainable at this stage.

## 2026-06-17

### Grader regression eval v1
- Turned the eval script into a small CLI tool while preserving the default behavior of running the full suite.
- Added `--list` to inspect available cases without making Claude calls, and `--case <name>` to run one targeted regression case.
- Case names are derived directly from the eval definitions and validated by `argparse`, preventing accidental runs caused by misspelled names.
- Added per-case runtime plus a summary with total runtime and failed case names.
- Verified `--help`, `--list`, invalid-case handling, and Python compilation without spending API tokens.

## 2026-07-08

### Langfuse observability — business metadata on traces
- Attached business dimensions to each grading trace so runs are filterable/sliceable in Langfuse: `user_id`, `question_id`, and the resulting `cefr_level`.
- Threaded `user_id` / `question_id` into `run_grader` as optional keyword-only params (defaults keep the eval harness, which has neither, calling it unchanged); `grade_answer` passes `answer.user_id` / `answer.question_id`.
- API gotcha: the Langfuse 4.7.1 client has no `update_current_trace()` (v3) or `update_current_observation()`, and `@observe()` doesn't take a `metadata` kwarg. `propagate_attributes` exists only as a module-level function, not a client method. The available equivalent is `update_current_span(metadata=...)` — checked `dir(get_client())` against the installed version before settling on it.
- Since `@observe()` creates a span observation, all three fields go into the metadata dict on that root span, set in one call after the graph completes (ids known up front, CEFR only known post-graph). No-op when tracing is disabled.
- Marked Phase 5 complete in README, scoped to **Langfuse LLM tracing**. A standalone OpenTelemetry pipeline (collector + exporter) is deferred to Phase 6, where it folds into the self-hosted Langfuse-on-K8s work.

## 2026-07-08

### Expanded writing seed questions (3 → 15)
- Added 12 new "Expression écrite" prompts (4 per task), keeping the existing levels and word-count ranges: Tâche 1 (A2, 60–120), Tâche 2 (B1, 120–150), Tâche 3 (B2, 120–180). Existing 3 questions untouched.
- Topics — T1: birthday invitation, thank-you after a stay, describing your neighbourhood, requesting course info. T2 (opinion): social media, remote work, public transport, learning a language early. T3 (argumentative, forum-debate style like the existing one): digital tools in education, car bans for the environment, work-life balance, cultural diversity at work.
- Gotcha: idempotency is keyed on `(exam_section, task_number, source)`, so multiple questions sharing a task_number must use distinct sources — otherwise all but one silently skip on insert. Gave each question a unique `source`; documented the constraint in a comment.
- Validated the literal before seeding (15 rows, 5 per task, all dedup keys unique, consistent fields/ranges), then seeded successfully.

## 2026-07-11

### Phase 3 kickoff — Speaking agent, slice 1: monologue grading
- Built the speaking equivalent of the Phase 2 flow: **audio upload → Whisper STT → speaking LangGraph grader → structured feedback.** Chose monologue grading first (over jumping to a live conversational examiner) to reuse the established architecture; TTS + multi-turn dialogue deferred.
- STT: `app/transcription.py` wraps OpenAI Whisper (`whisper-1`, `language=fr`), lazy client mirroring `grader._get_client()`. Added `openai` + `python-multipart` deps, `OPENAI_API_KEY` to config/.env.example. App still boots without the key; the upload endpoint returns 503.
- Grader: `app/speaking_grader.py` + `app/speaking_graph.py` mirror `grader.py`/`graph.py` (same fan-out/fan-in: `score ∥ find_errors → verify_errors → assemble`). Oral rubric = task_fulfillment / coherence / **lexis** / grammar. Reused `Correction`, `CEFRLevel`, the structured-call helper, and the `verify_errors` judge unchanged. Prompts are tuned for speech: fillers/false starts/repetitions are treated as normal, not errors.
- **Pronunciation is deliberately not graded** — a transcript loses the acoustic signal, so the prompt says so and the learner comment reminds them. Documented as a known limitation.
- No DB migration: transcript → `answers.content`, grade → `ai_feedback` (oral dims + `estimated_level` in the JSONB, same trick writing uses). New `/speaking` router (create/grade/read) mirrors the writing routers; a speaking answer is distinguished purely by its question's `exam_section`, and the routes reject a non-speaking question (400).
- Observability continues Phase 5: `@observe()` on `run_speaking_grader` + nodes, generation logging, trace metadata (user/question/CEFR). STT is its own trace (upload and grade are separate requests), logged as a `transcribe` generation.
- Seeded 3 Expression orale tasks (Tâches 1–3, A2/B1/B2). `word_count_min/max` are N/A for speech → set to 0; `time_limit_seconds` holds the speaking duration. Added `scripts/eval_speaking_grader.py` (transcript-based, no audio/OpenAI needed).
- Verified end-to-end: eval 3/3 pass (disfluencies not flagged; "les enfant"/"intéressants" agreement errors caught; weak answer not over-scored). Live audio path with a `say`-generated French clip: upload transcribed correctly → graded A2 with the pronunciation caveat in the comment → read back identical. Error paths confirmed: re-grade 409, non-speaking question 400, missing answer 404.

## 2026-07-12

### Phase 3 slice 2 — Speaking UI (browser audio recording)
- Wired the frontend to the `/speaking` endpoints: record a spoken answer with `MediaRecorder` → upload → show the Whisper transcript → show the oral grade. Mirrors the writing page's submit→grade→feedback UX.
- New `src/lib/use-audio-recorder.ts` hook: `getUserMedia` + `MediaRecorder`, elapsed timer, object-URL playback, mic-track + URL cleanup on stop/reset/unmount. Picks a Whisper-friendly container via `isTypeSupported` (webm → mp4 for Safari → ogg → default) and exposes the matching filename extension for the upload.
- New `src/app/speaking/[id]/page.tsx`: recorder controls (Record/Stop/playback/Re-record) + a two-step Submit (`transcribing` → `grading` → `done`) that surfaces the transcript before the grade. `SpeakingGradeReport` mirrors the writing report with oral dims (lexis) and the "Expression orale" band.
- `src/lib/api.ts`: added `SpeakingAnswerOut` / `SpeakingGrade` types + `submitSpeakingAnswer` (multipart FormData, no explicit Content-Type so the browser sets the boundary) + `gradeSpeakingAnswer`, reusing `errorFrom`.
- Home page (`src/app/page.tsx`) now routes by `exam_section` (speaking → `/speaking/[id]`, writing → `/questions/[id]`) — previously every question opened the writing text area — and groups the 18 questions under Writing / Speaking with section-aware metadata (speaking shows duration + a badge, not "0–0 words").
- Gotcha: the `react-hooks/set-state-in-effect` lint rule rejected detecting `MediaRecorder` support via `setState` in an effect. Used `useSyncExternalStore` (server snapshot = supported, client snapshot = real probe) instead — no effect, no hydration mismatch.
- Verified: `npm run lint` clean, `npm run build` passes (TypeScript + all routes: `/`, `/speaking/[id]`, `/questions/[id]`). Dev-server smoke: all routes 200, speaking shell SSRs, no runtime errors, writing flow unchanged.
- Manual browser pass (real mic, Chrome): record → Stop → playback → Submit → transcript → oral grade all working end-to-end; writing flow unchanged. Speaking UI slice confirmed complete.

## 2026-07-13

### Phase 3 slice 3 — Conversational examiner (backend, turn-based voice dialogue)
- Built the "voice agent": examiner speaks a prompt (TTS) → candidate answers (mic → STT) → examiner asks follow-ups over several turns → the dialogue is graded. Turn-based over HTTP; the persisted session is the source of truth (LangGraph's Postgres checkpointer isn't installed, so pausing one graph between HTTP turns isn't available — and a per-turn LLM call is simpler anyway).
- **First Alembic migration since schema v1**: new `speaking_sessions` table (`turns` JSONB, `answer_id` FK, status enum). Autogenerate missed dropping the enum on downgrade — added an explicit `Enum(...).drop()` so downgrade→upgrade round-trips (verified).
- New `app/tts.py` (OpenAI `gpt-4o-mini-tts`, reuses `OPENAI_API_KEY`, mirrors `transcription.py`) and `app/examiner.py` (pure turn logic like `grader.py`): `opening()` + `next_turn()` as structured Claude calls; a `MAX_CANDIDATE_TURNS=5` cap forces termination regardless of the model.
- New `app/routers/conversation.py`: `POST /speaking/sessions` (opening), `/turn` (multipart audio → STT → examiner reply → TTS), `/finish` (grade), `GET /sessions/{id}`. Examiner audio returned as base64 MP3 (no audio persisted). **Finish converges onto the monologue path**: builds an `answers` row from the candidate turns and reuses `run_speaking_grader` → `ai_feedback`, read back via the same `SpeakingFeedbackOut`. Factored `speaking_grader.feedback_fields()` so both routers share the grade→columns mapping.
- Observability: each turn is one Langfuse trace (span → `transcribe` / `examiner` / `tts` generations) tagged with session/user/question; finish reuses the traced grader.
- Gotcha: Anthropic requires `thinking.budget_tokens >= 1024` and `max_tokens > budget` — first cut used 512 and 400 → 400 error; bumped to 1024 / 1536.
- Verified: `eval_examiner` (text-only) passes — natural French follow-ups, ends exactly at the 5-turn cap. Live loop with `say` clips: opening (valid 24kHz MP3) → 2 turns (accurate STT + contextual questions + audio) → finish graded A2 (reused grader) with `answer_id` linked → session read-back shows all turns. Error paths: re-finish 409, turn-after-finish 409, writing-question 400. Migration round-trips. Monologue + writing paths unaffected.

## 2026-07-14

### Repurpose → self-hosted inference stack (reposition + scaffold)
- Reframed the repo around a self-hosted LLM serving stack (inference gateway → observability → K8s → Argo → vLLM serving); the TCF tutor becomes the workload that exercises it. Build plan: `docs/upgrade-plan.md` (moved in from the repo root).
- Reviewed the upgrade plan and settled three decisions with the user: **full pivot** of the framing; **rent a cloud GPU** for vLLM (the Mac has no CUDA, so local vLLM can't produce the GPU-metrics/quantization story); and a **GPU-free-first** build order — gateway + Prometheus/Grafana + kind K8s + Argo all run without a GPU, so vLLM is slotted in **last** on a rented GPU to minimize cost. This inverts the doc's vLLM-first order.
- Named the constraints up front: vLLM is text-only, so **STT (Whisper) + TTS stay on OpenAI**; **Claude stays as the "quality" backend** behind an `INFERENCE_BACKEND` (anthropic|openai|vllm) switch; grader structured output will need a guided-JSON path for the vLLM backend.
- This slice is docs + structure only (no app logic changed): new `docs/architecture-v2-infra.md` (target diagram + re-sequenced roadmap + decisions); monorepo skeleton dirs `gateway/ infra/ benchmarks/ pipeline/` each with a purpose+status README; README + CLAUDE.md rewritten to the infra framing with the real run/eval commands and new scope guardrails (measurement-first, code quality, sequencing).

## 2026-07-17

### Inference gateway — separate OpenAI-compatible service (first infra slice)
- Built `gateway/` as a standalone FastAPI service (own venv/deps), OpenAI-compatible `POST /v1/chat/completions` + `/metrics` + `/health`. Backend router keyed by `INFERENCE_BACKEND`: `anthropic` (default) translates to the Anthropic Messages API; `openai`/`vllm` forward to an `UPSTREAM_BASE_URL`. So vLLM later is a config change, not code.
- Structured output preserved across the boundary: the workload calls `chat.completions.parse(response_format=Pydantic)`; for the anthropic backend the gateway uses Anthropic's **native structured outputs** (`output_config.format`, thinking-compatible — the same mechanism `messages.parse` uses), normalizing the incoming OpenAI schema with Anthropic's own `transform_schema`. Reasoning control is now provider-agnostic: `_structured_call` takes `reasoning_effort` (low|medium|high); the gateway maps it to a thinking budget (verify/examiner → low, preserving the Session 5–6 latency tuning).
- Cross-cutting: Prometheus metrics (requests, latency histogram, tokens in/out, cost, in-flight), per-key token-bucket rate limiting (429), a per-model cost table.
- Migrated the whole workload through **one chokepoint** — `grader._structured_call` now uses `AsyncOpenAI(base_url=GATEWAY_URL)` instead of the Anthropic SDK; returns a normalized `Usage(input_tokens, output_tokens)` so `_log_generation` is unchanged. Dropped the direct `anthropic` dependency from the app; routers now map `openai.APIStatusError` → the gateway's status code (503/429/502). Backend gained `GATEWAY_URL` config; `ANTHROPIC_API_KEY` moved to the gateway.
- **Parity milestone met:** all three evals pass **through the gateway** with the anthropic backend — writing 3/3, speaking 3/3, examiner (ends at the 5-turn cap). Same model, structured output intact: routing is transparent.
- Metrics confirmed populated (`/metrics`); added `benchmarks/bench_gateway.py` (concurrent load → latency P50/95/99, QPS, output tok/sec, saved JSON). First run: 12 req @ concurrency 4 → QPS 1.35, P50 2.46s / P95 3.67s, ~123 output tok/sec.
- Gotcha: `budget_tokens < max_tokens` (unchanged from before) and the anthropic private schema path `anthropic.lib._parse._transform.transform_schema` — verified present in the gateway's anthropic 0.117.0.

## 2026-07-29

### Observability stack + reusable benchmark harness
- Stood up **Prometheus + Grafana** via docker-compose (`infra/observability/`). Prometheus scrapes the host gateway over `host.docker.internal:8001`; the `impl` label is a Prometheus *target* label (not app-side), so a second gateway implementation slots in with no code change. Grafana (`:3001`, anonymous) auto-provisions the **Inference Gateway** dashboard — QPS, error rate, request-latency p50/95/99, **gateway overhead** p50/95/99, upstream latency, tokens/sec, in-flight, cost — every panel faceted by `impl` so A/B is built in.
- **Metric contract hardened** for fair comparison: widened `gateway_request_latency_seconds` buckets (ms→s) and added `gateway_upstream_latency_seconds` + `gateway_overhead_seconds` (per-request total − upstream, fine sub-ms buckets). `backends.handle()` now returns `upstream_seconds`; `main.py` records upstream + overhead. Overhead is the metric the future Python-vs-Rust A/B turns on.
- Made the benchmark harness **implementation-agnostic**: `bench_gateway.py` gained `--label`, a concurrency **sweep** (per-level QPS + p50/95/99 + errors), and `--pid` peak-RSS sampling; added `mock_upstream.py` (deterministic OpenAI-compatible upstream, `MOCK_DELAY_MS` fast/realistic profiles) and `compare_results.py` (side-by-side A/B table). The canonical benchmark runs the gateway forward path against the mock, isolating gateway overhead.
- **Baseline captured** (`benchmarks/results/python-baseline.json`, forward→mock@1ms, limiter off): p50 9ms/p99 23ms at c=1; throughput peaks ~206 QPS at c=16 then degrades (Python ceiling); overhead p50 ≈4ms / p99 ≈24ms; peak RSS ≈93 MB; 0 errors. Validated the full loop: Prometheus target up, overhead quantiles resolve sub-ms.
- Gotchas: (1) the gateway's default rate limit (120/min) throttles a load test to ~2 QPS + triggers client 429-retries → **run benchmarks with the limiter set very high**; (2) `pgrep -f` for `--pid` matched the background shell wrapper, not the Python child — filter by `comm=python`.
- Scoped the future experiment in **`docs/rust-gateway-benchmark.md`**: hypothesis (single-request latency ~unchanged since I/O-bound; Rust wins on throughput ceiling, P99 under load, memory), method (same mock/load/dashboards/box), the exact metric contract, and the scorecard. **Rust gateway not built.**

## 2026-08-13

### Containerize the stack (Docker + full-stack compose)
- Split "containerize + K8s" in two: this slice is **Docker-only** (kubectl + helm aren't installed; kind + Docker are). Postgres runs **containerized fresh**; the backend entrypoint runs `alembic upgrade head` + seed on start.
- Added `gateway/Dockerfile` and `backend/Dockerfile` (both `python:3.11-slim`; all compiled deps resolved via manylinux wheels — no `build-essential` needed) + `.dockerignore`s + `backend/docker-entrypoint.sh` (migrate → seed → uvicorn).
- New `infra/compose/`: one-command full stack — `postgres:16` + gateway + backend + Prometheus + Grafana. Prometheus scrapes the gateway by **service DNS** (`gateway:8001`, `impl=python` target label); Grafana reuses the existing provisioning + dashboard unchanged. Kept separate from `infra/observability/` (which scrapes a *host-run* gateway for dev/benchmarks). Postgres isn't published to the host (avoids clashing with a host Postgres on 5432).
- **Verified end-to-end in containers:** `docker compose up --build` → backend entrypoint ran both migrations + seeded 18 questions → submitted + graded an answer (backend → gateway container → Anthropic) returning real CEFR feedback → Prometheus target `up` scraping `gateway:8001` with the grade's requests visible → Grafana healthy with the dashboard. `down -v` clean.
- Gotcha: leftover `tcf-prometheus`/`tcf-grafana` containers from the `infra/observability/` stack held :9090/:3001 — brought that stack down first.

## 2026-08-13 (later)

### Deploy to Kubernetes — kind + Helm (slice 3b-i)
- Split the K8s work: **this slice = app on kind via Helm** (Postgres + gateway + backend). In-cluster monitoring (kube-prometheus-stack) + **HPA on a gateway metric** is the next sub-slice (3b-ii) — it's large and needs the app running first.
- Hand-written Helm chart `infra/k8s/tcf/` (no external chart deps): Secret (with a fully-formed async `DATABASE_URL`), Postgres (Deployment + Service + PVC on kind's local-path storageclass), gateway + backend Deployments/Services. `helm lint` clean.
- **Migrations run in a backend `initContainer`, not a Helm pre-install hook** — a pre-install hook runs *before* Postgres exists (would fail); K8s retries the initContainer until Postgres is reachable, and `alembic upgrade` + seed are idempotent. App container overrides the image entrypoint to run uvicorn only (migrate is the init's job).
- Images: reused the compose-built images, tagged `tcf-gateway:dev` / `tcf-backend:dev`, `kind load`-ed (kind can't pull local images; `imagePullPolicy: IfNotPresent`).
- **Verified end-to-end on kind:** `helm install` → all 3 deployments rolled out → init ran both migrations + seeded 18 questions → `port-forward svc/tcf-backend` → submitted + graded an answer (backend pod → gateway pod → Anthropic) returning real A2 CEFR feedback. Teardown clean (`helm uninstall` + `kind delete cluster`).
- Gotcha: Langfuse values in `infra/compose/.env` were already double-quoted; naively re-quoting them into `values-secret.yaml` broke YAML — strip surrounding quotes when generating. Secrets live in a gitignored `values-secret.yaml` (only `*.example.yaml` committed; added a `values-secret.yaml` gitignore rule).

## 2026-08-13 (3b-ii)

### In-cluster monitoring + HPA — autoscale the gateway on a custom metric
- **kube-prometheus-stack** via Helm (`monitoring` ns), trimmed for kind (no alertmanager/node-exporter/kube-state-metrics/defaultRules; `serviceMonitorSelectorNilUsesHelmValues=false` so it picks up our ServiceMonitor). Values in `infra/k8s/monitoring/`.
- Chart gained flag-gated **ServiceMonitor** (scrapes the gateway `/metrics`, adds `impl=python` via relabel), **HPA** (`autoscaling/v2`, Pods metric on `gateway_inflight_requests`, avg target 5, 1→5), and a **mock upstream** (Deployment+Service from a new `benchmarks/Dockerfile.mock`) so the load demo is free. Gateway gained an `upstreamBaseUrl` value to point its forward path at the mock.
- **prometheus-adapter** exposes `gateway_inflight_requests` as a per-pod custom metric (`custom.metrics.k8s.io`) with an `avg by (pod)` rule pointed at the kps Prometheus.
- **Verified the full autoscaling loop on kind:** custom-metrics API served the metric; `kubectl get hpa` read it live (`TARGETS 0/5`, not `<unknown>`); driving load (bench → gateway → in-cluster mock) pushed in-flight to **12/5 per pod** and the HPA emitted `SuccessfulRescale … New size: 3; reason: pods metric gateway_inflight_requests above target` — gateway scaled **1 → 3**. Dashboard imported into the in-cluster Grafana via a labeled ConfigMap.
- Gotchas: (1) the first ~30s the HPA logged `FailedGetPodsMetric` until prometheus-adapter registered the metric — expected, then it scaled. (2) `kubectl port-forward` is a single connection and drops under 64-way load (bench showed "Connection error" tail) — a forwarding artifact, not a gateway failure; an in-cluster load generator would be cleaner. (3) HPA scale-**down** waits the default 5-min stabilization window.

## 2026-08-14

### Argo Workflows — model-eval → gate → promote pipeline (last GPU-free layer)
- Made the backend model **configurable**: `grader.MODEL = settings.inference_model` (env `INFERENCE_MODEL`, default sonnet); chart sets it on the backend Deployment. So "promoting a model" = patching that env (rolling update) — the same flow that will swap a vLLM-served version later. `eval_grader` grades via this model with no DB, so an eval pod with `INFERENCE_MODEL=<candidate>` evaluates that candidate.
- `pipeline/`: a `WorkflowTemplate` (`model-eval-promote`) with a DAG gate — `eval` (backend image runs the real `eval_grader` against the in-cluster gateway) → `promote` (`depends: eval.Succeeded`) → `notify-fail` (`depends: eval.Failed`). Promote appends `{model,result,promoted_at}` to a `tcf-model-registry` ConfigMap (kubectl+jq) and `kubectl set env deploy/tcf-backend INFERENCE_MODEL=<candidate>`. Plus RBAC (SA `tcf-pipeline`: workflowtaskresults + configmaps/deployments patch) and a **suspended** CronWorkflow (avoids scheduled Claude cost). Submit via `kubectl create` (no argo CLI needed).
- **Verified both gate outcomes on kind** (Argo v3.6.2, cluster install):
  - **Fail** (`candidate-model=not-a-real-model`): `eval` Failed fast (bad model errors, ~no Claude cost) → `promote` **Omitted** → `notify-fail` ran → registry stayed `[]`, backend model unchanged. Gate rejected cleanly.
  - **Pass** (`candidate-model=claude-sonnet-4-6`): real grader regression passed (~2 min) → `promote` ran → registry gained the entry → backend Deployment rolled to `INFERENCE_MODEL=claude-sonnet-4-6`.
- Gotcha: `.status.nodes` is a map (not a list) — jsonpath `range` over it errors; iterate the values instead. **The entire GPU-free infra stack is now built** (gateway → observability → containers → K8s+autoscaling → Argo pipeline).

## Next up
- **vLLM serving on a rented cloud GPU** — the last, GPU-dependent layer: OpenAI-compatible vLLM behind the gateway (`INFERENCE_BACKEND=vllm`), FP16-vs-AWQ benchmarks (reuse `bench_gateway.py`), GPU metrics into Grafana, GPU-aware HPA. The `INFERENCE_MODEL` promotion flow becomes the vLLM model-version swap.
- Future: the **Rust gateway** A/B (`docs/rust-gateway-benchmark.md`); deferred workload items (Speaking UI, WPM signal, pgvector RAG).
- Future: the **Rust gateway** experiment (see `docs/rust-gateway-benchmark.md`).
- Deferred workload items: conversational Speaking **UI** (wired to `/speaking/sessions`); Whisper `verbose_json` → words-per-minute fluency signal; scoring-reference RAG (pgvector).
- Perf round 2: grading still ~19s. Ideas: trim score-node prompt/output; try a faster model for find_errors; or stream partial results to the UI.

## Notes
- Two-terminal workflow established: one for backend (uvicorn), one for everything else.
- Commit prefix convention: `docs:`, `feat:`, `chore:`, `fix:`, `refactor:`.
