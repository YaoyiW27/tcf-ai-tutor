# Deploying the app path

Only the application layer is deployed: frontend, backend, gateway, database.
Kubernetes, Argo, Prometheus/Grafana and vLLM stay local — they are what the
stack was built to demonstrate, and hosting them costs real money while adding
nothing a single user can feel. (An EKS control plane alone costs more per month
than everything below.)

```
Browser ──► Vercel (Next.js + /api/backend proxy)
                    │  server-side, adds X-API-Key
                    ▼
            Fly: tcf-backend ──► Fly private net ──► Fly: tcf-gateway ──► Anthropic
                    │
                    ▼
              Neon Postgres + pgvector
```

The browser only ever talks to Vercel. The backend's secret is added by the
proxy server-side, so it is never in the bundle, and the backend needs no CORS
entry for the deployed frontend.

## 0. Accounts

Vercel, Neon, and Fly. Fly wants a card on file even inside its free
allowances.

## 1. Neon

Create a project, then get the connection string into the shape asyncpg accepts
— it will not connect otherwise.

First turn **Connection pooling off** in the connect dialog. Neon's pooler is
PgBouncer in transaction mode, and asyncpg leans on prepared statements — the
pair fails with `prepared statement "__asyncpg_stmt_1__" already exists`. One
user needs no pooler.

| Neon gives you | Use |
|---|---|
| `postgresql://…` | `postgresql+asyncpg://…` |
| `…-pooler.…` host | the host without `-pooler` (pooling off) |
| `?sslmode=require&channel_binding=require` | `?ssl=require` |

Drop the whole query string and write `?ssl=require`: both `sslmode` and
`channel_binding` are libpq spellings that asyncpg rejects outright.

Then enable the extension once, in the SQL Editor:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Alembic creates the tables on first backend boot, but the extension has to exist
before the `rubric_chunks` migration runs.

## 2. Gateway (deploy first)

The backend reaches it over the private network on boot, so it has to exist
first.

The gateway gets **no public IP**. It holds the Anthropic key and has no
authentication of its own, so anyone who reached it would have a free Claude
proxy. A private ingress address routes the backend to it through Fly's proxy —
which matters, because `.internal` resolves straight to the machine and skips
the proxy that implements auto-start, so a stopped gateway would just refuse the
connection.

```bash
cd gateway
fly apps create tcf-gateway
fly ips allocate-v6 --private -a tcf-gateway
fly ips list -a tcf-gateway     # private ingress only — no v4, no public v6
fly secrets set ANTHROPIC_API_KEY=sk-ant-… OPENAI_API_KEY=sk-…
fly deploy --ha=false           # one machine; HA doubles cost for one user
fly logs                        # expect: Uvicorn running on http://0.0.0.0:8001
```

## 3. Backend

Generate the shared secret first — this is the only thing standing between a
public URL and your model credits:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

```bash
cd backend
fly apps create tcf-backend
fly secrets set \
  DATABASE_URL='postgresql+asyncpg://…?ssl=require' \
  API_KEY='<the generated secret>' \
  OPENAI_API_KEY=sk-…
fly deploy --ha=false
```

Boot runs `alembic upgrade head`, seeds questions, then seeds rubrics. The
rubric step embeds through the gateway and is allowed to fail — grading then
runs without CEFR grounding rather than the API refusing to start. Check:

```bash
fly logs | grep entrypoint
curl -s https://tcf-backend.fly.dev/health                    # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' https://tcf-backend.fly.dev/questions   # 401
```

That 401 is the point of the exercise. If it returns 200, `API_KEY` did not take
and the API is open.

## 4. Frontend

On Vercel, set the project root to `frontend/` and add:

| Variable | Value |
|---|---|
| `BACKEND_URL` | `https://tcf-backend.fly.dev` |
| `BACKEND_API_KEY` | the same secret as the backend's `API_KEY` |

Neither is `NEXT_PUBLIC_`, and neither should ever be: that prefix inlines a
value into the browser bundle. Do **not** set `NEXT_PUBLIC_API_URL` in
production — it would make the browser call the backend directly, without the
secret.

## 5. Verify

```bash
curl -s https://<app>.vercel.app/api/backend/questions | head -c 200
```

Questions back means the whole chain works: browser → Vercel proxy → Fly backend
→ Neon. Then grade one essay in the UI and watch `fly logs` for the per-node
timings.

## Cost

Hosting sits inside the free allowances at one user's traffic; both Fly machines
scale to zero when idle and Neon suspends. The real spend is model calls — a few
LLM calls per grade plus one embedding, and Whisper/TTS on the speaking path.

Watch it in Grafana locally, or in the Anthropic and OpenAI dashboards.

## What is not deployed

Listening and reading. `ExamSection` has both values, but the seed corpus is 15
writing questions and 3 speaking ones, and there are no routes or pages for
either — the enum entries are placeholders, not features. Writing and speaking
work end to end.
