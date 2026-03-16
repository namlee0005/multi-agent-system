"""Thread-safe shared context store for the multi-agent debate pipeline."""

import threading
from typing import Any, Optional


class ContextStore:
    """
    Thread-safe key/value store with typed buckets for the debate pipeline.

    Bucket keys (lists):
      - proposals   : round-1 agent proposals
      - challenges  : round-2 challenge responses
      - artifacts   : <write_file> content accepted through the review gate
      - errors      : agent-level errors / review failures

    Scalar keys (any value):
      - project_description, round, round1_failed_agents, round2_failed_agents, etc.
    """

    # List-typed buckets — values are always lists internally
    LIST_KEYS = {"proposals", "challenges", "artifacts", "errors"}

    def __init__(self):
        self._store: dict[str, Any] = {k: [] for k in self.LIST_KEYS}
        self._lock = threading.RLock()

    # ── Scalar access ────────────────────────────────────────────────────────

    def set(self, key: str, value: Any) -> None:
        """Set a scalar value (overwrites). Use append() for list buckets."""
        with self._lock:
            self._store[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for key, or default if absent."""
        with self._lock:
            return self._store.get(key, default)

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            return self._store[key]

    # ── List-bucket access ───────────────────────────────────────────────────

    def append(self, bucket: str, entry: Any) -> None:
        """Append an entry to a list bucket (auto-creates non-LIST_KEYS buckets)."""
        with self._lock:
            if bucket not in self._store:
                self._store[bucket] = []
            if not isinstance(self._store[bucket], list):
                raise TypeError(f"Bucket '{bucket}' is a scalar key; use set() instead.")
            self._store[bucket].append(entry)

    def get_list(self, bucket: str) -> list:
        """Return a shallow copy of a list bucket (safe to iterate without holding lock)."""
        with self._lock:
            value = self._store.get(bucket, [])
            return list(value) if isinstance(value, list) else []

    # ── Snapshot ─────────────────────────────────────────────────────────────

    def snapshot(self, keys: Optional[list[str]] = None) -> dict:
        """
        Return a read-only shallow copy of the store.
        Passed to agents so they can read prior outputs without holding the lock.
        List buckets are copied; scalars are referenced.

        Args:
            keys: If provided, return only these keys (missing keys are silently
                  omitted). If None, return the full store.
        """
        with self._lock:
            items = (
                ((k, self._store[k]) for k in keys if k in self._store)
                if keys is not None
                else self._store.items()
            )
            return {k: (list(v) if isinstance(v, list) else v) for k, v in items}

    def __repr__(self) -> str:
        with self._lock:
            keys = list(self._store.keys())
        return f"ContextStore(keys={keys})"