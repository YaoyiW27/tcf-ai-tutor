# tcf-ai-tutor

A personal project to learn AI engineering by building a multi-agent
AI tutor for TCF Canada preparation.

## Goal

Primary: Gain hands-on experience with modern AI engineering — multi-agent
systems, voice AI, and production observability for LLM applications.

Secondary: Use it myself to prepare for TCF Canada.

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
- [ ] Phase 1: Schema design & first agent
- [ ] Phase 2: Writing AI Grader
- [ ] Phase 3: Speaking Voice Agent
- [ ] Phase 4: Multi-agent orchestration with LangGraph
- [ ] Phase 5: Observability (Langfuse + OpenTelemetry)
- [ ] Phase 6: Containerization & deployment

## Repository layout

```
tcf-ai-tutor/
├── frontend/         # Next.js 16 (App Router) + Tailwind v4 + shadcn/ui
├── backend/          # FastAPI service (Python 3.11)
├── docs/             # Schema & architecture notes
├── CLAUDE.md         # Guidance for Claude Code
└── README.md
```

## Quickstart

### Backend (FastAPI)

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# verify:
curl http://localhost:8000/health   # -> {"status":"ok"}
```

See [backend/README.md](backend/README.md) for details.

### Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev
# open http://localhost:3000
```

## Stack

**Frontend** (scaffolded):
- Next.js 16 (App Router, Turbopack) + React 19 + TypeScript
- Tailwind CSS v4
- shadcn/ui (Radix base, Nova preset)

**Backend** (scaffolded):
- Python 3.11, FastAPI, uvicorn[standard]

**AI** (planned):
- LangGraph — multi-agent orchestration
- Whisper — speech-to-text
- OpenAI / Anthropic API — LLM backbone

**Observability** (planned):
- Langfuse — LLM-specific tracing (prompts, costs, latency)
- OpenTelemetry — distributed tracing across services

**Infrastructure** (planned):
- Docker — containerization
- TBD: cloud deployment, database

## Positioning

This project sits at the intersection of AI engineering and DevOps —
showing how production engineering practices translate to LLM systems.