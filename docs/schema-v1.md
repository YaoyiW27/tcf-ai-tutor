# Schema v1 — Foundation

Status: Draft
Date: 2026-05-22
Scope: Minimum viable schema for TCF Writing practice with AI grading.

## Design philosophy

This is the foundational schema. It intentionally excludes agent
orchestration and observability tables. Those will be added as
schema-v2 when LangGraph and Langfuse are actually integrated —
designing them now would be speculative without real trace data.

The schema covers a single end-to-end flow: a user submits a TCF
Writing answer, an AI agent grades it, and the user sees feedback.

## Entities

### users

Authenticated via Google OAuth. No password management.

| Field      | Type      | Notes                        |
|------------|-----------|------------------------------|
| id         | UUID (PK) | System-generated             |
| email      | TEXT      | From Google OAuth            |
| name       | TEXT      | From Google OAuth            |
| created_at | TIMESTAMP | Account creation time        |

### questions

TCF Canada has a finite official question pool. AI-generated questions
are out of scope for v1.

| Field               | Type      | Notes                                                           |
|---------------------|-----------|-----------------------------------------------------------------|
| id                  | UUID (PK) | System-generated                                                |
| exam_section        | ENUM      | writing / speaking / listening / reading                        |
| task_number         | INT       | Tâche 1 / 2 / 3 (TCF Writing has 3 tasks)                       |
| prompt              | TEXT      | Question body shown to the user                                 |
| instructions        | TEXT      | Task requirements (e.g. word count, format)                     |
| time_limit_seconds  | INT       | Frontend countdown timer                                        |
| word_count_min      | INT       | Minimum word count (used by AI grader)                          |
| word_count_max      | INT       | Maximum word count                                              |
| difficulty_level    | ENUM      | A1 / A2 / B1 / B2 / C1 / C2 (CEFR)                              |
| source              | TEXT      | Source reliability tag (e.g. "Réussir", "Formation", "Opal")    |
| created_at          | TIMESTAMP |                                                                 |

### answers

Connects users and questions. Tracks both in-progress drafts and
submitted answers.

| Field                | Type           | Notes                                    |
|----------------------|----------------|------------------------------------------|
| id                   | UUID (PK)      |                                          |
| user_id              | UUID (FK)      | → users.id                               |
| question_id          | UUID (FK)      | → questions.id                           |
| content              | TEXT           | User's answer                            |
| status               | ENUM           | draft / submitted                        |
| time_spent_seconds   | INT            | Actual time used                         |
| started_at           | TIMESTAMP      | When user began the task                 |
| submitted_at         | TIMESTAMP NULL | When user submitted (NULL if draft)      |
| created_at           | TIMESTAMP      |                                          |
| updated_at           | TIMESTAMP      |                                          |

### ai_feedback

Created after a user submits an answer. One feedback per answer.

| Field             | Type      | Notes                                       |
|-------------------|-----------|---------------------------------------------|
| id                | UUID (PK) |                                             |
| answer_id         | UUID (FK) | → answers.id                                |
| total_score       | FLOAT     | Overall score (e.g. 4.5 / 6)                |
| dimension_scores  | JSON      | Per-dimension scores (grammar, vocab, etc.) |
| corrections       | JSON      | Specific corrections with explanations      |
| overall_comment   | TEXT      | AI's overall feedback                       |
| created_at        | TIMESTAMP |                                             |

#### Why JSON for dimension_scores and corrections?

These fields are written once (by the AI) and read together (displayed
to the user). They're rarely queried individually. JSON keeps the
schema simple and avoids over-normalization.

If access patterns shift later — e.g. cross-user analytics on grammar
scores — these can be migrated into normalized tables. This is a
deliberate trade-off, not a default choice.

## Relationships

One user has many answers. One question has many answers (across
users). Each submitted answer gets exactly one feedback.

## Out of scope for v1

The following are intentionally not in this schema. They'll be added
in later versions as the corresponding features are implemented:

- Agent orchestration tables (LangGraph state, agent_runs)
- Trace correlation fields (e.g. langfuse_trace_id)
- User progress aggregates (computed on-demand for v1)
- Error pattern tracking
- Multi-tenant / org support
- Soft deletes / audit logs