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

## Next up
- Phase 2 cont. — Step C: refactor the single-call grader into a LangGraph multi-agent graph
  - Decompose grading into focused nodes (per-dimension scoring + a skeptical correction-checker)
  - Goal: fix over-correction (only flag real errors), make each step traceable for the later Langfuse phase

## Notes
- Two-terminal workflow established: one for backend (uvicorn), one for everything else.
- Commit prefix convention: `docs:`, `feat:`, `chore:`, `fix:`, `refactor:`.