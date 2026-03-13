
import threading
import pytest
from context_store import ContextStore


def test_scalar_set_and_get():
    cs = ContextStore()
    cs.set("round", 1)
    assert cs.get("round") == 1


def test_scalar_default_when_missing():
    cs = ContextStore()
    assert cs.get("nonexistent", "default") == "default"


def test_scalar_overwrite():
    cs = ContextStore()
    cs.set("key", "first")
    cs.set("key", "second")
    assert cs.get("key") == "second"


def test_dict_style_set_get():
    cs = ContextStore()
    cs["project"] = "test project"
    assert cs["project"] == "test project"


def test_dict_style_missing_raises():
    cs = ContextStore()
    with pytest.raises(KeyError):
        _ = cs["no_such_key"]


def test_list_bucket_append_and_get():
    cs = ContextStore()
    cs.append("proposals", {"agent": "arch", "text": "Use microservices"})
    cs.append("proposals", {"agent": "backend", "text": "Use Postgres"})
    result = cs.get_list("proposals")
    assert len(result) == 2
    assert result[0]["agent"] == "arch"


def test_list_bucket_returns_copy():
    cs = ContextStore()
    cs.append("proposals", "item1")
    copy = cs.get_list("proposals")
    copy.append("item2")
    assert len(cs.get_list("proposals")) == 1, "Mutation of returned list must not affect store"


def test_all_default_list_buckets_exist():
    cs = ContextStore()
    for bucket in ("proposals", "challenges", "artifacts", "errors"):
        assert cs.get_list(bucket) == []


def test_append_to_scalar_key_raises():
    cs = ContextStore()
    cs.set("scalar_key", "value")
    with pytest.raises(TypeError):
        cs.append("scalar_key", "new_item")


def test_snapshot_is_isolated():
    cs = ContextStore()
    cs.set("phase", "round1")
    cs.append("proposals", "p1")
    snap = cs.snapshot()

    cs.set("phase", "round2")
    cs.append("proposals", "p2")

    assert snap["phase"] == "round1", "Snapshot scalar must reflect state at snapshot time"
    assert snap["proposals"] == ["p1"], "Snapshot list must reflect state at snapshot time"


def test_snapshot_contains_all_keys():
    cs = ContextStore()
    cs.set("foo", "bar")
    snap = cs.snapshot()
    assert "foo" in snap
    for bucket in ContextStore.LIST_KEYS:
        assert bucket in snap


def test_concurrent_append_correctness():
    """100 threads each append one item — final list must have exactly 100 items."""
    cs = ContextStore()
    n = 100

    def worker(i):
        cs.append("proposals", i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    result = cs.get_list("proposals")
    assert len(result) == n, f"Expected {n} items, got {len(result)}"
    assert sorted(result) == list(range(n)), "All items must be present, no duplicates or losses"


def test_concurrent_read_write_no_deadlock():
    """Mix of readers and writers must complete without deadlock."""
    cs = ContextStore()
    cs.set("counter", 0)
    errors = []

    def reader():
        try:
            for _ in range(50):
                cs.snapshot()
        except Exception as e:
            errors.append(e)

    def writer():
        try:
            for i in range(50):
                cs.set("counter", i)
                cs.append("errors", f"err-{i}")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=reader if i % 2 == 0 else writer) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert errors == [], f"Concurrent access errors: {errors}"
