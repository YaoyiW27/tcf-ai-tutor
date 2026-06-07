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


settings = Settings()
