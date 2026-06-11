# tcf-ai-tutor

**TCF Canada AI Tutor** — a LangGraph multi-node AI writing grader with a Next.js frontend. A personal project for hands-on AI engineering, motivated by preparing for TCF Canada.

## Stack

**Backend:** FastAPI · PostgreSQL · SQLAlchemy · Alembic · LangGraph · Anthropic
**Frontend:** Next.js · shadcn/ui · Tailwind · TypeScript

---

## Running the project

In development, run **two terminals at once**: one for the backend (`:8000`) and one for the frontend (`:3000`). Once both are up, open **http://localhost:3000** in your browser.

> Prerequisites: Python 3.11, Node.js, and a running PostgreSQL.

### Start the backend

In **terminal 1**, copy-paste from the repo root:

```bash
cd backend

# 1) Python virtualenv + dependencies
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2) Create the database role and database (one-time; set a password when prompted)
createuser tcf_app --pwprompt
createdb tcf_ai_tutor -O tcf_app

# 3) Config: copy the template, then edit .env with your DB password and Anthropic key
cp .env.example .env
#    Open .env and replace the placeholders with real values:
#    DATABASE_URL=postgresql+asyncpg://tcf_app:YOUR_PASSWORD@localhost:5432/tcf_ai_tutor
#    ANTHROPIC_API_KEY=sk-ant-YOUR_KEY

# 4) Create tables + seed sample questions
alembic upgrade head
python -m scripts.seed_questions
```

Then **run the API** (:8000) — copy-paste this block every time you start it:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

> The venv must be activated (prompt shows `(.venv)`) before running uvicorn, otherwise dependencies like `sqlalchemy` won't be found.

Verify: `curl http://localhost:8000/health` should return `{"status":"ok"}`. Interactive docs live at <http://localhost:8000/docs>.

### Start the frontend

In **terminal 2**, copy-paste from the repo root:

```bash
cd frontend

# 1) Dependencies
npm install

# 2) Config: backend URL (only needed to override the default of localhost:8000)
cp .env.example .env.local

# 3) Run the dev server (:3000)
npm run dev
```

Open **http://localhost:3000** — the home page fetches and renders the question list from the backend's `GET /questions`.

---

## What it is (and isn't)

**Is:**
- A multi-agent system that helps with TCF Writing and Speaking practice
- A learning project for AI infrastructure and observability
- A bridge project: applying DevOps/SRE practices (containers, tracing,
  monitoring) to LLM systems

**Isn't:**
- A complete TCF question bank
- A replacement for PrepMyFrench
- A startup or product play

## Status

- [x] Project scaffold
  - [x] Schema design ([docs/schema-v1.md](docs/schema-v1.md))
  - [x] Architecture sketch ([docs/architecture-v1.md](docs/architecture-v1.md))
  - [x] Frontend scaffold (Next.js + Tailwind + shadcn/ui)
  - [x] Backend scaffold (FastAPI + `/health`)
  - [x] Frontend-backend integration (CORS + env config)
- [x] Phase 1: Schema design & first agent
- [x] Phase 2: Writing AI Grader (LangGraph multi-node pipeline) — includes the multi-node orchestration originally scoped as Phase 4
- [ ] Phase 3: Speaking Voice Agent
- [~] Phase 5: Observability (Langfuse + OpenTelemetry) — in progress
- [ ] Phase 6: Containerization & deployment
  - Planned: self-hosted Langfuse on Kubernetes (Helm)

## Repository layout

```
tcf-ai-tutor/
├── frontend/         # Next.js 16 (App Router) + Tailwind v4 + shadcn/ui
├── backend/          # FastAPI service (Python 3.11)
├── docs/             # Schema & architecture notes
├── CLAUDE.md         # Guidance for Claude Code
└── README.md
```

See [backend/README.md](backend/README.md) for backend details.

## Positioning

This project sits at the intersection of AI engineering and DevOps —
showing how production engineering practices translate to LLM systems.
