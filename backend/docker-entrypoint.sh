#!/bin/sh
# Bring the schema up to date and seed sample questions (both idempotent), then
# start the API. Single-replica friendly; under K8s this becomes an init Job.
set -e

echo "[entrypoint] alembic upgrade head"
alembic upgrade head

echo "[entrypoint] seeding questions"
python -m scripts.seed_questions

echo "[entrypoint] starting API on :8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
