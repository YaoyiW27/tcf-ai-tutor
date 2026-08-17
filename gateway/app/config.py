"""Gateway configuration loaded from the environment / .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings for the inference gateway.

    ``inference_backend`` selects which model backend requests are routed to:
    ``anthropic`` (default — translate to the Anthropic Messages API),
    ``openai`` / ``vllm`` (forward to an OpenAI-compatible ``upstream_base_url``).
    Keys are read here (not left to each SDK's env lookup) so a single ``.env``
    configures the service.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    inference_backend: str = "anthropic"

    # anthropic backend
    anthropic_api_key: str | None = None

    # openai / vllm backends (forward path)
    upstream_base_url: str | None = None  # e.g. https://api.openai.com/v1 or the vLLM URL
    upstream_api_key: str | None = None

    # embeddings passthrough — always OpenAI (Anthropic has no embeddings API), so
    # it is independent of inference_backend: the chat backend can be anthropic or
    # vllm while embeddings stay on OpenAI. Kept metered/observable like chat.
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"

    # per-key token-bucket rate limiting
    rate_limit_per_min: float = 120.0
    rate_limit_burst: int = 20
    # Ceiling on tracked keys. The bucket map is keyed on the caller's raw
    # Authorization header, so it needs a bound — see the eviction note in
    # app.ratelimit for what is traded away when it is hit.
    rate_limit_max_keys: int = 10_000


settings = Settings()
