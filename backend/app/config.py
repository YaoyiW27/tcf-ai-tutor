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
    anthropic_api_key: str | None = None

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
