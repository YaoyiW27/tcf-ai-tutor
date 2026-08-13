# infra/compose/ — Full containerized stack

One command brings up the whole system in containers: Postgres + inference gateway +
backend (workload) + Prometheus + Grafana. No host Python/DB setup needed.

## Run
```bash
cd infra/compose
cp .env.example .env        # fill in ANTHROPIC_API_KEY (and OPENAI_API_KEY for speaking)
docker compose up --build
```
Run from this directory so `.env` is auto-loaded and the relative build/mount paths resolve.

- Backend API → http://localhost:8000 (`/health`, `/questions`, `/docs`)
- Gateway → http://localhost:8001
- Prometheus → http://localhost:9090 (`/targets` → `gateway` up)
- Grafana → http://localhost:3001 (anonymous; **Inference Gateway** dashboard)

The backend container runs `alembic upgrade head` + seeds sample questions on startup
(idempotent), then serves the API. Grade an answer (`POST /answers` → `POST /answers/{id}/grade`)
to see the full path — backend → gateway container → Anthropic — and live metrics in Grafana.

```bash
docker compose down       # stop
docker compose down -v    # stop + wipe the DB volume (fresh seed next run)
```

## Relationship to `infra/observability/`
- **`infra/observability/`** — Prometheus + Grafana only, scraping a **host-run** gateway
  (`host.docker.internal:8001`); for local dev + the benchmark harness.
- **`infra/compose/`** (this) — the **fully containerized** stack; Prometheus scrapes the
  gateway by service DNS (`gateway:8001`). Reuses the same Grafana provisioning + dashboard.

Postgres is not published to the host (avoids clashing with a host Postgres on 5432); the
backend reaches it in-network. Migrations run in the backend entrypoint here — under K8s
(next slice) they move to an init Job.
