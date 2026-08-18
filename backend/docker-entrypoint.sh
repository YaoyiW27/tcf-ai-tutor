#!/bin/sh
# Bring the schema up to date and seed sample questions (both idempotent), then
# start the API. Single-replica friendly; under K8s this becomes an init Job.
set -e

echo "[entrypoint] alembic upgrade head"
alembic upgrade head

echo "[entrypoint] seeding questions"
python -m scripts.seed_questions

# Rubric seeding embeds through the gateway, so it needs the gateway reachable
# and spends a little on embeddings. Both are bad reasons to fail a boot, and
# RAG is additive by design — an empty rubric_chunks just grades without CEFR
# grounding. So: attempt it, say what happened, never let it stop the API.
echo "[entrypoint] seeding rubrics (RAG grounding)"
python -m scripts.seed_rubrics \
  || echo "[entrypoint] rubric seed failed — grading will run without CEFR grounding"

echo "[entrypoint] starting API on :8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
