"""Venue volumes in the API: freshness, filtering, share maths, kind filter and outage behaviour."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aggregate as agg
from db import get_client
from main import app

NOW = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)


def vrow(dex="uniswap-v3-arc", vol="600", kind="dex", hours_old=1, **kw):
    base = {"dex_id": dex, "name": dex.title(), "kind": kind, "volume_24h_usd": vol, "active_pools": 4, "sample_pools": 200,
            "top_pool_name": "A / USDC", "top_pool_volume_usd": "300", "source": "geckoterminal",
            "fetched_at": (NOW - timedelta(hours=hours_old)).isoformat()}
    base.update(kw)
    return base


def test_sorted_by_volume_with_shares_that_sum_to_one():
    out = agg.build_venues([vrow("a", "100"), vrow("b", "300", kind="launchpad"), vrow("c", "600")], NOW)
    assert [v["dex_id"] for v in out] == ["c", "b", "a"]
    assert [round(v["share"], 3) for v in out] == [0.6, 0.3, 0.1]
    assert sum(v["share"] for v in out) == pytest.approx(1.0)
    assert out[1]["kind"] == "launchpad" and out[0]["top_pool_volume_usd"] == 300.0


def test_stale_empty_zero_and_malformed_rows_are_dropped():
    rows = [vrow("fresh", "10"),
            vrow("old", "10", hours_old=25),
            vrow("exactly-a-day", "10", hours_old=24),
            vrow("zero", "0"), vrow("neg", "-5"), vrow("junk", "abc"),
            vrow("badkind", "10", kind="exchange"),
            vrow("nostamp", "10", fetched_at=None), vrow("badstamp", "10", fetched_at="nope"),
            vrow("", "10")]
    assert sorted(v["dex_id"] for v in agg.build_venues(rows, NOW)) == ["exactly-a-day", "fresh"]
    assert agg.build_venues([], NOW) == [] and agg.build_venues(None, NOW) == []


def test_naive_timestamps_are_read_as_utc_and_missing_optional_fields_are_tolerated():
    naive = (NOW - timedelta(hours=2)).replace(tzinfo=None).isoformat()
    out = agg.build_venues([vrow("a", "5", fetched_at=naive, top_pool_name=None, top_pool_volume_usd=None, active_pools=None)], NOW)
    assert out[0]["top_pool_name"] is None and out[0]["top_pool_volume_usd"] is None and out[0]["active_pools"] == 0


@pytest.fixture(autouse=True)
def _dep():
    app.dependency_overrides[get_client] = lambda: "dummy"
    yield
    app.dependency_overrides.clear()


def fresh(rows):
    return [dict(r, fetched_at=datetime.now(timezone.utc).isoformat()) for r in rows]


def test_endpoint_lists_venues_and_filters_by_kind_keeping_share_relative_to_all(monkeypatch):
    import routes.venues as rv
    monkeypatch.setattr(rv, "fetch_venues", lambda c: fresh([vrow("a", "300"), vrow("b", "100", kind="launchpad")]))
    c = TestClient(app)
    allv = c.get("/venues").json()
    assert [v["dex_id"] for v in allv] == ["a", "b"] and allv[0]["share"] == pytest.approx(0.75)
    lp = c.get("/venues?kind=launchpad").json()
    assert [v["dex_id"] for v in lp] == ["b"] and lp[0]["share"] == pytest.approx(0.25)     # not 1.0
    assert c.get("/venues?kind=bogus").status_code == 422


def test_outage_is_a_503_not_an_empty_list(monkeypatch):
    import routes.venues as rv
    def boom(c): raise RuntimeError("relation venue_market_data does not exist")
    monkeypatch.setattr(rv, "fetch_venues", boom)
    r = TestClient(app).get("/venues")
    assert r.status_code == 503 and "temporarily unavailable" in r.json()["detail"]


def test_all_stale_rows_give_an_empty_list_not_old_numbers(monkeypatch):
    import routes.venues as rv
    monkeypatch.setattr(rv, "fetch_venues", lambda c: [vrow("a", "300", hours_old=1000)])
    assert TestClient(app).get("/venues").json() == []
