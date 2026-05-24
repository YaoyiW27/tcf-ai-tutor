# Backend — TCF AI Tutor

FastAPI service for the TCF AI Tutor. Currently exposes a single health endpoint; agents, graders, and orchestration will be added in later phases.

## Requirements

- Python 3.11 (the venv was created against `python3.11`)

## Setup

From the project root:

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Run the dev server

With the venv activated:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then in another shell:

```bash
curl http://localhost:8000/health
# -> {"status":"ok"}
```

Interactive docs: <http://localhost:8000/docs>

## Project layout

```
backend/
├── app/
│   ├── __init__.py
│   └── main.py          # FastAPI app + GET /health
├── requirements.txt     # pinned deps (pip freeze)
├── .gitignore
└── README.md
```
