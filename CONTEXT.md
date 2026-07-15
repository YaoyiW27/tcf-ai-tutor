# tcf-ai-tutor — Domain glossary

> This file is the single source of truth for project terminology.
> Every term here has been resolved through a /grill-with-docs session.
> Agents: read this before writing code. Use these terms in commits, variables, and docs.

---

## Tutor workload

The application layer: FastAPI backend + LangGraph graders + Next.js UI.
It is the *consumer* of LLM inference, not the provider.
Avoid: "the app" (ambiguous — could mean gateway or frontend).

## Writing grader

A LangGraph multi-node graph that evaluates a user's written French response
against TCF Canada scoring rubrics. Produces a structured score + feedback.
Avoid: "evaluator" (overloaded — could mean the Argo model-eval pipeline).

## Speaking grader

Scores a user's spoken French response. Input: audio → Whisper STT → text →
LangGraph grading chain. Output: structured score + feedback.
Avoid: "speech grader" (inconsistent with codebase naming).

## Voice examiner

A turn-based conversational loop: the system asks a TCF-style question via TTS,
the user answers via microphone, the system grades and asks the next question.
NOT: a batch grader. It maintains conversational state across turns.
Avoid: "interviewer" (too informal), "oral exam" (TCF-specific term is "expression orale").

## Inference gateway *(in progress)*

The HTTP service between the tutor workload and LLM backends.
Responsibilities: request validation, token accounting, rate limiting,
backend routing, metrics exposition, SSE passthrough.
NOT: the LLM itself, the tutor app logic, or a general-purpose API gateway.
Avoid: "proxy" (too generic), "middleware" (implies framework-level, not service-level).

## Backend switch

The `INFERENCE_BACKEND` env var (`anthropic` | `openai` | `vllm`) that tells the
gateway which downstream to route to.
Avoid: "model selector" (confusing — the model *name* is a separate config).

## Token accounting

Per-request recording of `prompt_tokens` + `completion_tokens` + `estimated_cost`,
written to the metrics store after each response completes.
NOT: pre-request token *estimation* (a separate concern, not yet built).
Avoid: "token counting" when you mean the post-hoc record.

## Model pipeline *(planned)*

Argo Workflows pipeline: pull model weights → run eval suite → compare against
baseline → rolling-update the vLLM deployment on pass, else notify.
NOT: the CI/CD pipeline for the app code (that's GitHub Actions).
Avoid: "deployment pipeline" (ambiguous with app deployment).

## Eval suite

The set of benchmark tasks (TTFT, tokens/sec, P50/95/99 latency, QPS, cost/req)
run by the model pipeline to decide whether a candidate model beats the baseline.
Avoid: "benchmark" alone (could mean the tutor's grading accuracy or the infra perf).

## Materialization order

The build sequence for infra layers: gateway → monitoring → K8s → Argo → vLLM.
GPU-independent layers are built first on Mac; vLLM is wired in last on a rented GPU.
This is a deliberate ordering, not an arbitrary backlog.

---

*Last updated by /grill-with-docs — [date]*
*Format: Term → definition → NOT (what it isn't) → Avoid (aliases that cause confusion)*
