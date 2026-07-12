# Architecture v1 — Writing Practice Flow

Status: Draft
Date: 2026-05-22
Scope: End-to-end flow for the Writing AI Grader (Phase 2).

## System overview

```
┌─────────────────────────────────────────────────────────────┐
│                        User Browser                          │
│                                                              │
│   [Writing Page]  →  [Submit]  →  [Feedback Page]            │
└──────────┬─────────────────────────────────┬─────────────────┘
           │                                 │
           ▼                                 ▼
┌─────────────────────────────────────────────────────────────┐
│                    Backend API (TBD)                         │
│                                                              │
│   POST /answers       GET /answers/:id/feedback              │
└──────────┬─────────────────────────────────┬─────────────────┘
           │                                 │
           ▼                                 │
┌────────────────────┐                       │
│  Grading Agent     │                       │
│  (LangGraph)       │                       │
│                    │                       │
│  - parse answer    │                       │
│  - call LLM        │                       │
│  - structure score │                       │
└──────────┬─────────┘                       │
           │                                 │
           ▼                                 ▼
┌─────────────────────────────────────────────────────────────┐
│                  PostgreSQL (TBD)                            │
│                                                              │
│   users  ←  answers  →  ai_feedback                          │
│              ↑                                               │
│         questions                                            │
└─────────────────────────────────────────────────────────────┘
```

## Flow: user submits an answer

1. User opens a Writing question page
2. Frontend creates an `answers` row with `status=draft`
3. User types and submits
4. Backend updates `status=submitted`, triggers Grading Agent
5. Grading Agent reads question + answer, calls LLM
6. Agent writes structured feedback to `ai_feedback`
7. Frontend polls / reads feedback, displays to user

## Components — to be chosen

These are deliberately not pinned in v1. They'll be chosen at
implementation time based on real constraints.

- **Frontend**: TBD (likely Next.js)
- **Backend**: TBD (likely Python — FastAPI)
- **Agent framework**: LangGraph (committed in README)
- **Database**: PostgreSQL (assumed)
- **LLM provider**: TBD (OpenAI or Anthropic)

## Observability — out of scope for v1

Langfuse + OpenTelemetry will be added once the basic flow is
working. They are not on the v1 critical path.

## Speaking (Phase 3) — reuses this flow

The Speaking ("Expression orale") path mirrors the flow above with a
speech-to-text step in front: **audio upload → Whisper STT (transcript) →
speaking LangGraph grader → `ai_feedback`.** The grader is a direct mirror of
the writing grader (same fan-out/fan-in graph, shared `Correction` / verify
step) with an oral rubric, and it reuses the existing `answers` / `ai_feedback`
tables (transcript in `answers.content`; no migration). Pronunciation is not
graded — a transcript carries no acoustic signal. See `app/transcription.py`,
`app/speaking_grader.py`, `app/speaking_graph.py`, `app/routers/speaking.py`.