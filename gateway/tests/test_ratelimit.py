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


def test_bucket_map_stays_bounded_under_a_flood_of_new_keys(monkeypatch):
    """The map is keyed on the caller's Authorization header, so it needs a ceiling.

    Without one, anyone can grow the gateway's memory without limit by sending a
    fresh random key on every request.
    """
    monkeypatch.setattr(rl.time, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(rl.settings, "rate_limit_max_keys", 10)
    monkeypatch.setattr(rl.settings, "rate_limit_per_min", 60.0)
    monkeypatch.setattr(rl.settings, "rate_limit_burst", 5)
    rl._buckets.clear()

    for i in range(500):
        rl.allow(f"junk-{i}")

    assert len(rl._buckets) <= 10


def test_actively_throttled_key_is_not_the_eviction_candidate(monkeypatch):
    """Every check moves its key to the hot end, including a denied one.

    A caller who is actively being limited keeps touching its bucket, so LRU
    eviction reaches the colder keys first rather than resetting the limit on
    the caller the limiter is currently holding back.
    """
    monkeypatch.setattr(rl.time, "monotonic", lambda: 1000.0)  # frozen: no refill
    monkeypatch.setattr(rl.settings, "rate_limit_max_keys", 5)
    monkeypatch.setattr(rl.settings, "rate_limit_per_min", 60.0)
    monkeypatch.setattr(rl.settings, "rate_limit_burst", 2)
    rl._buckets.clear()

    rl.allow("hot")
    rl.allow("hot")
    assert rl.allow("hot") is False  # now throttled

    for i in range(50):
        rl.allow(f"cold-{i}")
        rl.allow("hot")  # keeps getting denied, keeps the bucket hot

    assert "hot" in rl._buckets, "the throttled bucket was evicted"
    assert rl.allow("hot") is False, "eviction reset the limit"
    assert len(rl._buckets) <= 5
