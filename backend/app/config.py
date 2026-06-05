"""Application configuration loaded from the environment / .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings read from environment variables (and a local .env file).

    DATABASE_URL must use the asyncpg driver, e.g.
    postgresql+asyncpg://user:password@host:5432/dbname
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str


settings = Settings()
