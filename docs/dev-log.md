# Dev Log

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

## 2026-06-10 Session 4

### Langfuse observability — Step 1
- Installed langfuse==4.7.1, wired to Langfuse Cloud (US region)
- Decorated top-level run_grader with @observe(), flush in finally block
- Langfuse client init is conditional: keys missing → tracing disabled silently
- First trace confirmed in dashboard: run_grader span with full input/output/latency

## 2026-06-11 Session 5

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

## 2026-06-15 Session 6

### Langfuse observability — Step 2 follow-up
- Fixed a tracing gap: `verify_errors` was documented as a Langfuse generation, but the code discarded its Anthropic token usage before `graph.py` could log it.
- `grader.verify_errors()` now returns `(corrections, usage)` when it calls Claude, and `([], None)` when it short-circuits because there are no candidate corrections.
- `verify_errors_node` now logs a `verify_errors` generation only when a model call actually happened, so Langfuse distinguishes "node ran with no candidates" from "node made a Claude call".
- Verified syntax with `.venv/bin/python -m compileall app`.

## 2026-06-16 Session 7

### Grader regression eval v0
- Added `backend/scripts/eval_grader.py`, a small human-readable eval script for the LangGraph writing grader. It calls the real grader with fixed examples and prints PASS/FAIL, estimated CEFR/NCLC/band, and corrections.
- Covered three regression checks: polite imparfait should not be flagged (`Je voulais...`), obvious plural/agreement errors should be detected (`des pomme`, `très gentils`), and a very weak short answer should not be over-scored.
- First run passed 3/3. Runtime was roughly 50s for three real Claude-backed grading runs, reinforcing that LLM evals should stay small, targeted, and explainable at this stage.

## 2026-06-17 Session 8

### Grader regression eval v1
- Turned the eval script into a small CLI tool while preserving the default behavior of running the full suite.
- Added `--list` to inspect available cases without making Claude calls, and `--case <name>` to run one targeted regression case.
- Case names are derived directly from the eval definitions and validated by `argparse`, preventing accidental runs caused by misspelled names.
- Added per-case runtime plus a summary with total runtime and failed case names.
- Verified `--help`, `--list`, invalid-case handling, and Python compilation without spending API tokens.

## Next up
- Langfuse, deepen tracing (now that the entry point is wired):
  - Attach trace metadata (answer id, question id / task number, estimated_level) so traces are filterable and linkable back to the stored feedback.
  - Verify end-to-end against a real Langfuse project; decide cloud vs self-hosted (self-host is Docker → folds into Phase 6).
  - Revisit flush strategy: per-run flush is fine at current volume; switch to background-exporter-only (flush on app shutdown) if it adds latency.
- Perf round 2: grading still ~19s. Ideas: trim score-node prompt/output; try a faster model for find_errors; or stream partial results to the UI (per-node Langfuse spans above will show where the time goes)
- Phase 3: Speaking agent (Whisper + LangGraph + TTS)
- Future: self-host Langfuse on K8s via Helm chart (Phase 6)
- Expand seed questions to 15-20

## Notes
- Two-terminal workflow established: one for backend (uvicorn), one for everything else.
- Commit prefix convention: `docs:`, `feat:`, `chore:`, `fix:`, `refactor:`.
