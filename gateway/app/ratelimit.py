"""In-memory per-key token-bucket rate limiting.

One bucket per API key (the request's Authorization value). Single-process only —
fine for local/dev; a distributed limiter (Redis) would replace this before
running multiple gateway replicas.
"""

import time
from collections import OrderedDict
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


# Buckets, least-recently-used first. Bounded on purpose: the key is the
# caller's raw Authorization header, so an unbounded map lets anyone grow the
# gateway's memory without limit just by sending a new random key each request.
#
# Eviction is LRU, and every check — allowed or denied — moves its key to the
# hot end, so a caller who is actively being throttled stays hot and is not the
# eviction candidate. The trade-off worth naming: under a flood of distinct junk
# keys large enough to cycle the whole map, some real bucket does get dropped,
# and a dropped bucket comes back full. That direction is a limiter *bypass*,
# not a denial of service against the caller, and bounded memory is the more
# important property. A shared store (Redis) with per-key TTL is what removes
# the trade-off rather than balancing it.
_buckets: "OrderedDict[str, TokenBucket]" = OrderedDict()
_lock = Lock()


def _evict_to(limit: int) -> None:
    """Drop least-recently-used buckets until at most ``limit`` remain."""
    while len(_buckets) > limit:
        _buckets.popitem(last=False)


def allow(key: str) -> bool:
    """Rate-limit check for ``key`` using the configured rate/burst."""
    with _lock:
        bucket = _buckets.get(key)
        if bucket is None:
            # Make room *before* inserting, so the new bucket cannot evict itself.
            _evict_to(max(settings.rate_limit_max_keys - 1, 0))
            bucket = TokenBucket(
                rate_per_sec=settings.rate_limit_per_min / 60.0,
                capacity=settings.rate_limit_burst,
            )
            _buckets[key] = bucket
        else:
            _buckets.move_to_end(key)
        return bucket.allow()
