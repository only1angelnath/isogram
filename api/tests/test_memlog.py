"""memlog is read-only diagnostics: it must format cleanly everywhere and never raise."""

import memlog


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
