"""SnapshotCache behaviour, plus the routes that use it (/projects, /stats)."""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from cache import SnapshotCache
from db import get_client
from main import app


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_fresh_snapshot_is_served_without_recomputing():
    clock = Clock()
    cache = SnapshotCache(ttl=60, max_stale=900, clock=clock)
    calls = []
    compute = lambda: calls.append(1) or len(calls)
    assert cache.get("k", compute) == 1
    clock.t = 59
    assert cache.get("k", compute) == 1
    assert len(calls) == 1


def test_stale_snapshot_is_served_immediately_and_refreshed_in_background():
    clock = Clock()
    cache = SnapshotCache(ttl=60, max_stale=900, clock=clock)
    gate = threading.Event()
    state = {"n": 0}

    def compute():
        state["n"] += 1
        if state["n"] > 1:
            gate.wait(2)  # the refresh is slow; the caller must not wait for it
        return state["n"]

    assert cache.get("k", compute) == 1
    clock.t = 120
    started = time.monotonic()
    assert cache.get("k", compute) == 1          # stale value, instantly
    assert time.monotonic() - started < 0.5
    gate.set()
    deadline = time.monotonic() + 2
    while cache.get("k", compute) == 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert cache.get("k", compute) == 2


def test_too_old_snapshot_is_rebuilt_in_the_foreground():
    clock = Clock()
    cache = SnapshotCache(ttl=60, max_stale=900, clock=clock)
    n = {"v": 0}
    compute = lambda: n.__setitem__("v", n["v"] + 1) or n["v"]
    assert cache.get("k", compute) == 1
    clock.t = 5000
    assert cache.get("k", compute) == 2


def test_failed_rebuild_serves_the_previous_snapshot_but_cold_failure_raises():
    clock = Clock()
    cache = SnapshotCache(ttl=60, max_stale=900, clock=clock)
    with pytest.raises(RuntimeError):
        cache.get("k", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert cache.get("k", lambda: "ok") == "ok"
    clock.t = 5000  # too old for background refresh, so a foreground rebuild that then fails
    assert cache.get("k", lambda: (_ for _ in ()).throw(RuntimeError("db down"))) == "ok"


def test_concurrent_cold_callers_share_one_rebuild():
    cache = SnapshotCache(ttl=60, max_stale=900)
    calls = []

    def compute():
        calls.append(1)
        time.sleep(0.2)
        return "v"

    results = []
    threads = [threading.Thread(target=lambda: results.append(cache.get("k", compute))) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results == ["v"] * 8
    assert len(calls) == 1


@pytest.fixture
def api(monkeypatch):
    app.dependency_overrides[get_client] = lambda: "dummy-client"
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_projects_route_reads_once_per_snapshot(api, monkeypatch):
    import routes.projects as projects_route

    reads = []

    def fake_projects(c):
        reads.append(1)
        return [{"id": "isogram", "name": "Isogram", "category": "infra", "contracts": ["0xaaa"],
                 "created_at": "2026-09-16T00:00:00+00:00"}]

    monkeypatch.setattr(projects_route, "fetch_projects", fake_projects)
    monkeypatch.setattr(projects_route, "fetch_all_latest_scores", lambda c: [])
    monkeypatch.setattr(projects_route, "fetch_market_data", lambda c: [])
    monkeypatch.setattr(projects_route, "fetch_holders", lambda c: [])
    monkeypatch.setattr(projects_route, "fetch_socials", lambda c: [])
    first = api.get("/projects")
    second = api.get("/projects")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(reads) == 1


def test_stats_route_reads_once_per_snapshot(api, monkeypatch):
    import routes.network as network_route

    reads = []
    monkeypatch.setattr(network_route, "fetch_projects", lambda c: reads.append(1) or [])
    monkeypatch.setattr(network_route, "fetch_all_latest_scores", lambda c: [])
    monkeypatch.setattr(network_route, "fetch_network_stats", lambda c: None)
    assert api.get("/stats").status_code == 200
    assert api.get("/stats").status_code == 200
    assert len(reads) == 1
