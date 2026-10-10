"""Holder counts in the API: staleness, unknown vs zero, which projects get them, outage tolerance."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aggregate as agg
from db import get_client
from main import app

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def hrow(count=2521, hours_old=1, address="0xaaa"):
    return {"contract_address": address, "holders_count": count, "fetched_at": (NOW - timedelta(hours=hours_old)).isoformat()}


def test_fresh_count_is_returned_and_zero_is_a_real_value():
    assert agg.build_holders(hrow(2521), NOW) == 2521
    assert agg.build_holders(hrow(0), NOW) == 0


def test_unknown_when_no_row_null_count_or_unreadable():
    assert agg.build_holders(None, NOW) is None and agg.build_holders({}, NOW) is None
    assert agg.build_holders(hrow(None), NOW) is None                      # cached 404: explorer does not index it
    assert agg.build_holders(hrow("abc"), NOW) is None
    assert agg.build_holders(hrow(-4), NOW) is None
    assert agg.build_holders(hrow(True), NOW) is None
    assert agg.build_holders(hrow("2521"), NOW) == 2521                    # numeric string from a bigint column


def test_older_than_72_hours_is_unknown():
    assert agg.build_holders(hrow(5, hours_old=72), NOW) == 5
    assert agg.build_holders(hrow(5, hours_old=73), NOW) is None
    assert agg.build_holders({"holders_count": 5, "fetched_at": None}, NOW) is None
    assert agg.build_holders({"holders_count": 5, "fetched_at": "nope"}, NOW) is None


def test_naive_timestamp_is_read_as_utc():
    naive = (NOW - timedelta(hours=2)).replace(tzinfo=None).isoformat()
    assert agg.build_holders({"holders_count": 9, "fetched_at": naive}, NOW) == 9


PROJECTS = [
    {"id": "tok", "name": "Tok", "category": "meme", "contracts": ["0xAAA", "0xother"]},
    {"id": "pad", "name": "Pad", "category": "launchpad", "contracts": ["0xbbb"]},
    {"id": "dex", "name": "Dex", "category": "dex", "contracts": ["0xccc"]},
]
ROWS = [hrow(10, address="0xaaa"), hrow(20, address="0xbbb"), hrow(30, address="0xccc")]


def test_only_token_like_projects_get_holders_by_primary_contract():
    out = {s["id"]: s for s in agg.build_all_summaries(PROJECTS, [], None, NOW, ROWS)}
    assert out["tok"]["holders"] == 10 and out["pad"]["holders"] == 20
    assert out["dex"]["holders"] is None                    # DeFi contracts are not tokens here


@pytest.fixture(autouse=True)
def _dep():
    app.dependency_overrides[get_client] = lambda: "dummy"
    yield
    app.dependency_overrides.clear()


def _patch(monkeypatch, holders_rows=None, boom=False):
    import routes.projects as pr
    monkeypatch.setattr(pr, "fetch_projects", lambda c: [dict(p, created_at=None) for p in PROJECTS])
    monkeypatch.setattr(pr, "fetch_project", lambda c, pid: next((dict(p, created_at=None) for p in PROJECTS if p["id"] == pid), None))
    monkeypatch.setattr(pr, "fetch_all_latest_scores", lambda c: [])
    monkeypatch.setattr(pr, "fetch_latest_scores_for_project", lambda c, pid: [])
    monkeypatch.setattr(pr, "fetch_market_data", lambda c: [])
    monkeypatch.setattr(pr, "fetch_market_for_address", lambda c, a: None)

    def fresh(rows): return [dict(r, fetched_at=datetime.now(timezone.utc).isoformat()) for r in rows]
    def raising(*a, **k): raise RuntimeError("relation token_holders does not exist")

    monkeypatch.setattr(pr, "fetch_holders", raising if boom else (lambda c: fresh(holders_rows or [])))
    monkeypatch.setattr(pr, "fetch_holders_for_address",
                        raising if boom else (lambda c, a: next(iter(fresh([r for r in (holders_rows or []) if r["contract_address"] == a])), None)))


def test_list_and_detail_include_holders(monkeypatch):
    _patch(monkeypatch, ROWS)
    c = TestClient(app)
    body = {p["id"]: p for p in c.get("/projects").json()}
    assert body["tok"]["holders"] == 10 and body["dex"]["holders"] is None
    assert c.get("/projects/pad").json()["holders"] == 20


def test_holder_outage_does_not_break_projects(monkeypatch):
    _patch(monkeypatch, boom=True)
    c = TestClient(app)
    r = c.get("/projects")
    assert r.status_code == 200 and all(p["holders"] is None for p in r.json())
    assert c.get("/projects/tok").json()["holders"] is None
