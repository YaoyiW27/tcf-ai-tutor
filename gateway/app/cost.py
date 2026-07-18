"""Per-request cost estimation from token usage.

Prices are USD per 1,000,000 tokens, ``(input, output)``. This is a small static
table, not billing truth — enough to expose a cost/request metric. Unknown models
cost 0 (self-hosted vLLM is effectively free per token).
"""

PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (15.0, 75.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "gpt-4o-mini": (0.15, 0.60),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate request cost in USD from token counts."""
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return input_tokens / 1_000_000 * price_in + output_tokens / 1_000_000 * price_out
