"""Token-bucket rate limiting logic (deterministic — clock is monkeypatched)."""

import app.ratelimit as rl
from app.ratelimit import TokenBucket


def test_token_bucket_allows_up_to_capacity_then_denies(monkeypatch):
    monkeypatch.setattr(rl.time, "monotonic", lambda: 1000.0)  # frozen: no refill
    bucket = TokenBucket(rate_per_sec=1.0, capacity=3)
    assert [bucket.allow() for _ in range(3)] == [True, True, True]
    assert bucket.allow() is False


def test_token_bucket_refills_after_time_passes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(rl.time, "monotonic", lambda: clock["t"])
    bucket = TokenBucket(rate_per_sec=2.0, capacity=2)
    assert bucket.allow() and bucket.allow()  # drain the 2 tokens
    assert bucket.allow() is False
    clock["t"] += 1.0                          # +1s -> +2 tokens (rate 2/s)
    assert bucket.allow() is True


def test_allow_uses_separate_buckets_per_key(monkeypatch):
    monkeypatch.setattr(rl.time, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(rl.settings, "rate_limit_per_min", 60.0)  # 1 token/sec
    monkeypatch.setattr(rl.settings, "rate_limit_burst", 1)       # burst of 1
    rl._buckets.clear()
    assert rl.allow("user-a") is True    # a's only token
    assert rl.allow("user-a") is False   # a exhausted
    assert rl.allow("user-b") is True    # b has its own bucket
