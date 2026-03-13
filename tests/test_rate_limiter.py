
import time
import threading
import pytest
from rate_limiter import TokenBucket, RateLimiter


def test_token_bucket_initial_tokens_allow_immediate_acquire():
    bucket = TokenBucket(rpm=60)
    start = time.monotonic()
    bucket.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.1, "First acquire should be near-instant when bucket starts full"


def test_token_bucket_drains_and_blocks():
    rpm = 6  # 1 token per 10 seconds — very slow
    bucket = TokenBucket(rpm=rpm)
    # Drain all tokens first
    for _ in range(rpm):
        bucket._tokens -= 1.0
    bucket._tokens = 0.0

    start = time.monotonic()
    bucket.acquire()
    elapsed = time.monotonic() - start
    # Should have waited roughly 10s/6 ≈ 1.67s per token, but we just need > 0.5s
    assert elapsed > 0.5, f"Expected wait after drain, got {elapsed:.2f}s"


def test_token_bucket_respects_rpm_cap():
    rpm = 10
    bucket = TokenBucket(rpm=rpm)
    # Manually set tokens above rpm — refill should cap at rpm
    bucket._tokens = 0.0
    bucket._last_refill = time.monotonic() - 120  # simulate 2 minutes elapsed
    bucket._refill()
    assert bucket._tokens == rpm, "Tokens should be capped at rpm"


def test_rate_limiter_default_backends():
    rl = RateLimiter()
    assert "claude" in rl._buckets
    assert "gemini" in rl._buckets


def test_rate_limiter_custom_rpm():
    rl = RateLimiter(limits_rpm={"mybackend": 30})
    assert "mybackend" in rl._buckets
    assert rl._buckets["mybackend"]._rpm == 30


def test_rate_limiter_auto_creates_unknown_backend():
    rl = RateLimiter()
    rl.acquire("newbackend")  # Should not raise; creates bucket with default 10 rpm
    assert "newbackend" in rl._buckets


def test_rate_limiter_per_backend_isolation():
    rl = RateLimiter(limits_rpm={"fast": 600, "slow": 1})
    # Drain slow bucket
    rl._buckets["slow"]._tokens = 0.0

    # fast should acquire immediately
    start = time.monotonic()
    rl.acquire("fast")
    fast_elapsed = time.monotonic() - start
    assert fast_elapsed < 0.2, "Fast backend should not be affected by slow backend state"


def test_rate_limiter_thread_safety():
    """Multiple threads acquiring from the same bucket should not raise."""
    rl = RateLimiter(limits_rpm={"shared": 600})
    errors = []

    def worker():
        try:
            rl.acquire("shared")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert errors == [], f"Thread safety errors: {errors}"
