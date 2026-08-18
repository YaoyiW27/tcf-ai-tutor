import logging
from contextlib import asynccontextmanager
from secrets import compare_digest

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import answers, conversation, feedback, questions, speaking

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.api_key:
        logger.warning(
            "API_KEY is not set — every endpoint is open. Fine on a laptop; set "
            "it before this is reachable from the internet."
        )
    yield


app = FastAPI(title="TCF AI Tutor Backend", lifespan=lifespan)

# Reachable without the shared secret: the health probe, which a platform needs
# before it has any credentials to offer. Everything else stays behind it —
# including /docs and /openapi.json, which describe the whole surface.
PUBLIC_PATHS = frozenset({"/health"})


def _allowed_origins() -> list[str]:
    return [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    """Gate every non-public path on the shared secret, when one is configured.

    No key configured means no gate, so the local workflow is unchanged. That
    default is deliberate but load-bearing: a deployment must set ``API_KEY``,
    and startup logs a warning when it hasn't, because the failure mode is
    silent — a working, entirely open API that bills to your model credits.
    """
    if (
        settings.api_key
        and request.method != "OPTIONS"  # CORS preflight carries no headers to check
        and request.url.path not in PUBLIC_PATHS
    ):
        # Constant-time: a plain == leaks the secret one character at a time to
        # anyone who can measure response timing.
        if not compare_digest(request.headers.get("x-api-key", ""), settings.api_key):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(questions.router)
app.include_router(answers.router)
app.include_router(feedback.router)
app.include_router(speaking.router)
app.include_router(conversation.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
