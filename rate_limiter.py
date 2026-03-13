
"""Thread-safe token bucket rate limiter with per-backend limits."""

import threading
import time


_DEFAULT_LIMITS_RPM = {
    "claude": 10,
    "gemini": 15,
}


class TokenBucket:
    """Token bucket for a single backend."""

    def __init__(self, rpm: int):
        self._rpm = rpm
        self._tokens = float(rpm)
        self._refill_rate = rpm / 60.0  # tokens per second
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._rpm, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now

    def acquire(self):
        """Block until a token is available, then consume one."""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._refill_rate
            time.sleep(wait)


class RateLimiter:
    """Per-backend rate limiter. Thread-safe singleton-friendly."""

    def __init__(self, limits_rpm: dict[str, int] | None = None):
        resolved = {**_DEFAULT_LIMITS_RPM, **(limits_rpm or {})}
        self._buckets: dict[str, TokenBucket] = {
            backend: TokenBucket(rpm) for backend, rpm in resolved.items()
        }
        self._lock = threading.Lock()

    def acquire(self, backend: str):
        """Acquire a token for the given backend, blocking if necessary."""
        with self._lock:
            if backend not in self._buckets:
                self._buckets[backend] = TokenBucket(10)
            bucket = self._buckets[backend]
        bucket.acquire()
