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


def test_cache_is_bounded():
    cache = SnapshotCache(ttl=60, max_stale=900, max_entries=3)
    for i in range(10):
        cache.get(f"k{i}", lambda i=i: i)
    assert len(cache._entries) <= 3
    assert cache.get("k9", lambda: "recomputed") == 9  # newest survived


def test_metrics_series_are_snapshotted(api, monkeypatch):
    import routes.metrics as metrics_route

    reads = {"daily": 0, "tokens": 0}

    def fake_daily(c, days):
        reads["daily"] += 1
        return []

    def fake_tokens(c, days, token):
        reads["tokens"] += 1
        return []

    monkeypatch.setattr(metrics_route, "fetch_network_daily", fake_daily)
    monkeypatch.setattr(metrics_route, "fetch_pipeline_status", lambda c: {"data_through": None})
    monkeypatch.setattr(metrics_route, "fetch_token_daily", fake_tokens)
    for _ in range(2):
        assert api.get("/metrics/network/daily?days=7").status_code == 200
        assert api.get("/metrics/tokens/daily?days=7").status_code == 200
    assert api.get("/metrics/network/daily?days=14").status_code == 200  # a different window is its own snapshot
    assert reads == {"daily": 2, "tokens": 1}


def test_large_responses_are_gzipped(api, monkeypatch):
    import routes.projects as projects_route

    many = [{"id": f"p{i}", "name": f"Project {i}", "category": "token", "contracts": [f"0x{i:040x}"],
             "created_at": "2026-09-16T00:00:00+00:00"} for i in range(300)]
    monkeypatch.setattr(projects_route, "fetch_projects", lambda c: many)
    monkeypatch.setattr(projects_route, "fetch_all_latest_scores", lambda c: [])
    monkeypatch.setattr(projects_route, "fetch_market_data", lambda c: [])
    monkeypatch.setattr(projects_route, "fetch_holders", lambda c: [])
    monkeypatch.setattr(projects_route, "fetch_socials", lambda c: [])
    resp = api.get("/projects", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") == "gzip"
    assert len(resp.json()) == 300  # the client decodes it transparently
    assert resp.headers.get("access-control-expose-headers") or resp.headers.get("x-ratelimit-limit")


def test_warm_targets_use_the_calls_the_dashboard_makes(monkeypatch):
    import main

    seen = []
    monkeypatch.setattr(main.projects, "cached_project_summaries", lambda c: seen.append("projects"))
    monkeypatch.setattr(main.network, "cached_network_summary", lambda c: seen.append("stats"))
    monkeypatch.setattr(main.metrics, "network_daily", lambda days, client: seen.append(f"nd{days}"))
    monkeypatch.setattr(main.metrics, "tokens_daily", lambda days, token, client: seen.append(f"td{days}:{token}"))
    monkeypatch.setattr(main.metrics, "contracts_top", lambda days, limit, client: seen.append(f"top{days}:{limit}"))
    for _label, call in main._warm_targets("c"):
        call()
    assert seen == ["projects", "stats", "nd7", "nd8", "nd14", "nd30", "td8:USDC", "td7:None", "td14:None", "td30:None", "top7:15"]
