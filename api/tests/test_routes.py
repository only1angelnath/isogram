"""
Route-level tests. No live Supabase connection: the `get_client` dependency
is overridden to a dummy value, and each db.fetch_* function used by a route
is monkeypatched at the point it was imported into that route module (since
`from db import fetch_x` binds a name at import time — patching db.fetch_x
after that wouldn't reach the route). Same "fabricated data, no network"
intent as ingestion/tests/test_worker.py and scoring/tests/test_compute_scores.py.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import get_client
from main import app

PROJECTS = [
    {"id": "isogram", "name": "Isogram", "category": "infra", "contracts": ["0xaaa"], "created_at": "2026-09-16T00:00:00+00:00"},
    {"id": "quiet-project", "name": "Quiet Project", "category": "dex", "contracts": ["0xbbb"], "created_at": "2026-09-20T00:00:00+00:00"},
]

SCORES = [
    {
        "project_id": "isogram",
        "score": "0.8",
        "tvl_usd": "500",
        "usdc_gas_7d": "10",
        "unique_users_7d": 3,
        "computed_at": "2026-09-22T00:00:00+00:00",
    }
    # "quiet-project" deliberately has no score row yet.
]


@pytest.fixture(autouse=True)
def override_get_client():
    app.dependency_overrides[get_client] = lambda: "dummy-client"
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_health():
    c = TestClient(app)
    resp = c.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_list_projects(client, monkeypatch):
    import routes.projects as projects_route

    monkeypatch.setattr(projects_route, "fetch_projects", lambda c: PROJECTS)
    monkeypatch.setattr(projects_route, "fetch_all_latest_scores", lambda c: SCORES)

    resp = client.get("/projects")
    assert resp.status_code == 200
    body = resp.json()
    by_id = {p["id"]: p for p in body}
    assert by_id["isogram"]["score"] == 0.8
    assert by_id["quiet-project"]["score"] is None


def test_get_project_found(client, monkeypatch):
    import routes.projects as projects_route

    monkeypatch.setattr(projects_route, "fetch_project", lambda c, pid: PROJECTS[0])
    monkeypatch.setattr(projects_route, "fetch_latest_scores_for_project", lambda c, pid: SCORES)

    resp = client.get("/projects/isogram")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "isogram"
    assert body["score"] == 0.8
    assert body["contracts"] == ["0xaaa"]


def test_get_project_not_found(client, monkeypatch):
    import routes.projects as projects_route

    monkeypatch.setattr(projects_route, "fetch_project", lambda c, pid: None)

    resp = client.get("/projects/does-not-exist")
    assert resp.status_code == 404


def test_gas_top(client, monkeypatch):
    import routes.gas as gas_route

    monkeypatch.setattr(gas_route, "fetch_projects", lambda c: PROJECTS)
    monkeypatch.setattr(gas_route, "fetch_all_latest_scores", lambda c: SCORES)

    resp = client.get("/gas/top")
    assert resp.status_code == 200
    body = resp.json()
    # Only the scored project should appear — quiet-project has no gas figure yet.
    assert len(body) == 1
    assert body[0]["id"] == "isogram"


def test_tvl_top_respects_limit(client, monkeypatch):
    import routes.tvl as tvl_route

    many_scores = [
        {"project_id": f"p{i}", "score": "0.1", "tvl_usd": str(i), "usdc_gas_7d": "0",
         "unique_users_7d": 0, "computed_at": "2026-09-22T00:00:00+00:00"}
        for i in range(5)
    ]
    many_projects = [{"id": f"p{i}", "name": f"P{i}", "category": None, "contracts": [], "created_at": None} for i in range(5)]

    monkeypatch.setattr(tvl_route, "fetch_projects", lambda c: many_projects)
    monkeypatch.setattr(tvl_route, "fetch_all_latest_scores", lambda c: many_scores)

    resp = client.get("/tvl/top?limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["id"] == "p4"  # highest tvl_usd first


def test_scores_for_project(client, monkeypatch):
    import routes.scores as scores_route

    monkeypatch.setattr(scores_route, "fetch_project", lambda c, pid: PROJECTS[0])
    monkeypatch.setattr(scores_route, "fetch_latest_scores_for_project", lambda c, pid: SCORES)

    resp = client.get("/scores/isogram")
    assert resp.status_code == 200
    assert resp.json()["score"] == 0.8


def test_badge_svg_with_score(client, monkeypatch):
    import routes.badge as badge_route

    monkeypatch.setattr(badge_route, "fetch_project", lambda c, pid: PROJECTS[0])
    monkeypatch.setattr(badge_route, "fetch_latest_scores_for_project", lambda c, pid: SCORES)

    resp = client.get("/badge/isogram.svg")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert "0.80" in resp.text


def test_badge_svg_no_score_shows_honest_fallback():
    import routes.badge as badge_route

    with TestClient(app) as c:
        badge_route.fetch_project = lambda client_, pid: PROJECTS[1]
        badge_route.fetch_latest_scores_for_project = lambda client_, pid: []
        resp = c.get("/badge/quiet-project.svg")
        assert resp.status_code == 200
        assert "insufficient data" in resp.text


def test_badge_svg_project_not_found(client, monkeypatch):
    import routes.badge as badge_route

    monkeypatch.setattr(badge_route, "fetch_project", lambda c, pid: None)

    resp = client.get("/badge/nope.svg")
    assert resp.status_code == 404


def test_stats_endpoint(client, monkeypatch):
    import routes.network as network_route

    monkeypatch.setattr(network_route, "fetch_projects", lambda c: PROJECTS)
    monkeypatch.setattr(network_route, "fetch_all_latest_scores", lambda c: SCORES)
    monkeypatch.setattr(
        network_route,
        "fetch_network_stats",
        lambda c: {
            "total_volume_7d": "999.5",
            "total_tx_7d": 10,
            "total_unique_users_7d": 3,
            "computed_at": "2026-09-22T00:00:00+00:00",
        },
    )

    resp = client.get("/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_projects"] == 2
    assert body["total_scored"] == 1  # only "isogram" has a score row in SCORES
    assert body["total_tvl_usd"] == 500.0
    assert body["avg_score"] == 0.8  # only "isogram" scored, so avg == its own score
    assert body["total_volume_7d"] == 999.5


def test_stats_endpoint_no_network_stats_yet_returns_nulls(client, monkeypatch):
    import routes.network as network_route

    monkeypatch.setattr(network_route, "fetch_projects", lambda c: PROJECTS)
    monkeypatch.setattr(network_route, "fetch_all_latest_scores", lambda c: SCORES)
    monkeypatch.setattr(network_route, "fetch_network_stats", lambda c: None)

    resp = client.get("/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_volume_7d"] is None
    assert body["total_tx_7d"] is None


def test_no_route_accepts_a_write():
    """
    Per docs/AUDIT.md: this is a read-only public data service. Confirm no
    route in the app is registered for a write HTTP method.
    """
    write_methods = {"POST", "PUT", "PATCH", "DELETE"}
    for route in app.routes:
        methods = getattr(route, "methods", set()) or set()
        assert not (methods & write_methods), f"{route.path} exposes a write method: {methods}"
