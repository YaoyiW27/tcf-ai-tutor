"""In-memory per-key token-bucket rate limiting.

One bucket per API key (the request's Authorization value). Single-process only —
fine for local/dev; a distributed limiter (Redis) would replace this before
running multiple gateway replicas.
"""

import time
from threading import Lock

from app.config import settings


class TokenBucket:
    """Classic token bucket: refills at ``rate`` tokens/sec up to ``capacity``."""

    def __init__(self, rate_per_sec: float, capacity: int) -> None:
        self.rate = rate_per_sec
        self.capacity = capacity
        self.tokens = float(capacity)
        self.updated = time.monotonic()

    def allow(self) -> bool:
        """Consume one token if available; return whether the request is allowed."""
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


_buckets: dict[str, TokenBucket] = {}
_lock = Lock()


def allow(key: str) -> bool:
    """Rate-limit check for ``key`` using the configured rate/burst."""
    with _lock:
        bucket = _buckets.get(key)
        if bucket is None:
            bucket = TokenBucket(
                rate_per_sec=settings.rate_limit_per_min / 60.0,
                capacity=settings.rate_limit_burst,
            )
            _buckets[key] = bucket
        return bucket.allow()
