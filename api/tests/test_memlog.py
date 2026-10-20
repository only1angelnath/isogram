"""memlog is read-only diagnostics: it must format cleanly everywhere and never raise."""

import memlog
from cache import snapshots


def test_describe_has_every_field():
    line = memlog.describe()
    assert line.startswith("MEM ")
    for field in ("rss=", "peak=", "cgroup=", "threads=", "inflight=", "snapshots="):
        assert field in line


def test_inflight_counter_never_goes_negative():
    memlog.request_finished()
    memlog.request_finished()
    assert memlog.inflight() == 0
    memlog.request_started()
    assert memlog.inflight() == 1
    memlog.request_finished()
    assert memlog.inflight() == 0


def test_missing_platform_values_print_as_na(monkeypatch):
    monkeypatch.setattr(memlog, "rss_mb", lambda: None)
    monkeypatch.setattr(memlog, "peak_mb", lambda: None)
    monkeypatch.setattr(memlog, "cgroup_mb", lambda: None)
    assert "rss=n/a peak=n/a cgroup=n/a" in memlog.describe()


def test_start_is_off_when_disabled(monkeypatch):
    monkeypatch.setenv("MEMLOG_SECONDS", "0")
    assert memlog.start() is False


def test_deep_size_grows_with_content_and_counts_shared_objects_once():
    small = memlog.deep_size([{"a": "x"}])
    big = memlog.deep_size([{"a": "x" * 10_000}])
    assert big > small + 9_000
    shared = "y" * 10_000
    assert memlog.deep_size([shared, shared, shared]) < 2 * memlog.deep_size([shared])


def test_deep_size_follows_object_attributes_and_slots():
    class Plain:
        def __init__(self):
            self.payload = "z" * 5_000

    class Slotted:
        __slots__ = ("payload",)

        def __init__(self):
            self.payload = "z" * 5_000

    assert memlog.deep_size(Plain()) > 5_000
    assert memlog.deep_size(Slotted()) > 5_000


def test_describe_snapshots_lists_largest_first():
    snapshots.clear()
    try:
        snapshots._store("small", [1, 2, 3])
        snapshots._store("big", ["q" * 1000 for _ in range(500)])
        line = memlog.describe_snapshots()
        assert line.startswith("MEMDETAIL snapshots total=")
        assert line.index("big=") < line.index("small=")
    finally:
        snapshots.clear()


def test_trace_report_is_none_while_tracing_is_off():
    assert memlog.describe_trace() is None
