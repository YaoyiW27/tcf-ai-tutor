"""Application configuration loaded from the environment / .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings read from environment variables (and a local .env file).

    DATABASE_URL must use the asyncpg driver, e.g.
    postgresql+asyncpg://user:password@host:5432/dbname

    ANTHROPIC_API_KEY is read here (rather than relying on the SDK's own
    env lookup) because pydantic-settings loads .env into this object, not
    into os.environ — so the SDK wouldn't see a key that lives only in .env.
    It is optional so the app still boots (and the store/read paths still
    work) without it; the grade endpoint returns 503 when it's unset.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str

    # Comma-separated browser origins allowed to call this API directly. The
    # deployed frontend calls its own server-side proxy instead, so this only
    # needs the local dev origins unless a browser on another host talks to the
    # API directly.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Shared secret required on every request except /health. Unset — the local
    # default — means no auth at all, which is fine on a laptop and is exactly
    # what must not ship: anyone who finds a public URL would spend your model
    # credits. Startup logs a warning when it is unset.
    api_key: str | None = None

    # Inference gateway base URL. All text-LLM calls (graders + examiner) go
    # through the gateway (see app.grader), which holds the provider keys and
    # routes to the configured backend (default Claude). STT/TTS still call
    # OpenAI directly (openai_api_key below).
    gateway_url: str = "http://localhost:8001"

    # Model the graders/examiner request from the gateway. Configurable so the
    # Argo eval pipeline can evaluate + promote a candidate model by setting
    # INFERENCE_MODEL (rolling the backend), without a code change.
    inference_model: str = "claude-sonnet-4-6"

    # Kept for reference / local scripts; the backend no longer calls Anthropic
    # directly (the gateway does). Safe to leave set in .env.
    anthropic_api_key: str | None = None

    # Scoring-reference RAG: the embedding model requested from the gateway's
    # /v1/embeddings passthrough (always OpenAI-served) and its vector dimension.
    # The dimension must match the `Vector(...)` column in app.models.RubricChunk
    # and the migration; changing the model means a new migration + re-seed.
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # OpenAI API key, used only for Whisper speech-to-text on the Speaking path
    # (POST /speaking/answers). Read here for the same reason as
    # ANTHROPIC_API_KEY above (pydantic-settings loads .env into this object,
    # not os.environ). Optional: the app still boots without it; the speaking
    # upload endpoint returns 503 when it's unset.
    openai_api_key: str | None = None

    # Langfuse (LLM observability). Optional — tracing is disabled when unset.
    # Read here for the same reason as ANTHROPIC_API_KEY above: pydantic-settings
    # loads .env into this object, not os.environ, so the SDK can't see keys that
    # live only in .env. app.graph passes these to the Langfuse client.
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None


settings = Settings()
