"""
Third-party market data in the API (ADR-005): quality rules, staleness, which projects get
it, and that a market-data outage can never take /projects down. No network, no database.
"""

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


def row(**kw):
    base = {
        "contract_address": "0xaaa", "price_usd": "1.5", "fdv_usd": "2000000", "market_cap_usd": None,
        "liquidity_usd": "50000", "volume_24h_usd": "25000", "coingecko_coin_id": None,
        "source": "geckoterminal", "fetched_at": (NOW - timedelta(hours=1)).isoformat(),
    }
    base.update(kw)
    return base


# ------------------------------------------------------------------ quality rules

def test_healthy_market_is_ok_and_keeps_fdv():
    m = agg.build_market(row(), NOW)
    assert m["quality"] == "ok" and m["price_usd"] == 1.5 and m["fdv_usd"] == 2_000_000.0
    assert m["liquidity_usd"] == 50_000.0 and m["volume_24h_usd"] == 25_000.0
    assert m["source"] == "geckoterminal" and m["listed_on_coingecko"] is False


def test_thin_liquidity_keeps_price_but_withholds_fdv():
    m = agg.build_market(row(liquidity_usd="4336", fdv_usd="161593600", volume_24h_usd="57"), NOW)
    assert m["quality"] == "thin" and m["price_usd"] == 1.5
    assert m["fdv_usd"] is None and m["market_cap_usd"] is None


def test_unknown_liquidity_counts_as_thin():
    assert agg.build_market(row(liquidity_usd=None), NOW)["quality"] == "thin"


def test_liquidity_exactly_at_the_floor_is_not_thin():
    assert agg.build_market(row(liquidity_usd="10000", volume_24h_usd="5000"), NOW)["quality"] == "ok"
    assert agg.build_market(row(liquidity_usd="9999.99"), NOW)["quality"] == "thin"


def test_big_pool_nobody_trades_is_inactive_and_has_no_fdv():
    """The real 2026-10-09 case: $39M of 'liquidity', $1 of volume, a $357B 'FDV'."""
    m = agg.build_market(row(price_usd="3569.61", fdv_usd="356961282367", liquidity_usd="39081622",
                             volume_24h_usd="1"), NOW)
    assert m["quality"] == "inactive" and m["fdv_usd"] is None and m["price_usd"] == pytest.approx(3569.61)


def test_volume_at_one_percent_of_liquidity_is_ok_and_below_is_inactive():
    assert agg.build_market(row(liquidity_usd="100000", volume_24h_usd="1000"), NOW)["quality"] == "ok"
    assert agg.build_market(row(liquidity_usd="100000", volume_24h_usd="999"), NOW)["quality"] == "inactive"
    assert agg.build_market(row(liquidity_usd="100000", volume_24h_usd=None), NOW)["quality"] == "inactive"


def test_coingecko_listing_flag():
    assert agg.build_market(row(coingecko_coin_id="usd-coin"), NOW)["listed_on_coingecko"] is True
    assert agg.build_market(row(coingecko_coin_id="  "), NOW)["listed_on_coingecko"] is False


# ------------------------------------------------------------------ availability

def test_no_row_no_price_or_zero_price_means_no_market():
    assert agg.build_market(None, NOW) is None and agg.build_market({}, NOW) is None
    assert agg.build_market(row(price_usd=None), NOW) is None
    assert agg.build_market(row(price_usd="0"), NOW) is None
    assert agg.build_market(row(price_usd="garbage"), NOW) is None


def test_rows_older_than_24_hours_are_unavailable():
    assert agg.build_market(row(fetched_at=(NOW - timedelta(hours=24)).isoformat()), NOW) is not None
    assert agg.build_market(row(fetched_at=(NOW - timedelta(hours=24, seconds=1)).isoformat()), NOW) is None
    assert agg.build_market(row(fetched_at=None), NOW) is None
    assert agg.build_market(row(fetched_at="not a date"), NOW) is None


def test_timestamp_without_timezone_is_read_as_utc():
    naive = (NOW - timedelta(hours=2)).replace(tzinfo=None).isoformat()
    assert agg.build_market(row(fetched_at=naive), NOW)["quality"] == "ok"
    assert agg.build_market(row(fetched_at="2026-10-09T10:00:00Z"), NOW) is not None


# ------------------------------------------------------------------ who gets market data

PROJECTS = [
    {"id": "tok", "name": "Tok", "category": "meme", "contracts": ["0xAAA", "0xother"]},
    {"id": "usd", "name": "Usd", "category": "stablecoin", "contracts": ["0xbbb"]},
    {"id": "dex", "name": "Dex", "category": "dex", "contracts": ["0xccc"]},
    {"id": "bare", "name": "Bare", "category": "token", "contracts": []},
]
MARKET_ROWS = [row(contract_address="0xaaa"), row(contract_address="0xbbb", price_usd="1.0"),
               row(contract_address="0xccc", price_usd="9")]


def test_only_token_and_stablecoin_projects_get_market_by_primary_contract():
    out = {s["id"]: s for s in agg.build_all_summaries(PROJECTS, [], MARKET_ROWS, NOW)}
    assert out["tok"]["market"]["price_usd"] == 1.5          # matched case-insensitively
    assert out["usd"]["market"]["price_usd"] == 1.0
    assert out["dex"]["market"] is None                       # DeFi is never priced here
    assert out["bare"]["market"] is None


def test_no_market_rows_means_market_none_everywhere():
    assert all(s["market"] is None for s in agg.build_all_summaries(PROJECTS, [], None, NOW))


# ------------------------------------------------------------------ routes

@pytest.fixture(autouse=True)
def _client_dep():
    app.dependency_overrides[get_client] = lambda: "dummy"
    yield
    app.dependency_overrides.clear()


def _patch_routes(monkeypatch, market_rows=None, market_row=None, boom=False):
    import routes.projects as pr
    monkeypatch.setattr(pr, "fetch_projects", lambda c: [dict(p, created_at=None) for p in PROJECTS])
    monkeypatch.setattr(pr, "fetch_project", lambda c, pid: next((dict(p, created_at=None) for p in PROJECTS if p["id"] == pid), None))
    monkeypatch.setattr(pr, "fetch_all_latest_scores", lambda c: [])
    monkeypatch.setattr(pr, "fetch_latest_scores_for_project", lambda c, pid: [])

    def fresh(rows):
        return [dict(r, fetched_at=datetime.now(timezone.utc).isoformat()) for r in rows]

    def raising(*a, **k):
        raise RuntimeError("relation token_market_data does not exist")

    monkeypatch.setattr(pr, "fetch_market_data", raising if boom else (lambda c: fresh(market_rows or [])))
    monkeypatch.setattr(pr, "fetch_market_for_address",
                        raising if boom else (lambda c, a: fresh([market_row])[0] if market_row else None))


def test_list_includes_market_for_tokens(monkeypatch):
    _patch_routes(monkeypatch, market_rows=MARKET_ROWS)
    body = {p["id"]: p for p in TestClient(app).get("/projects").json()}
    assert body["tok"]["market"]["quality"] == "ok" and body["tok"]["market"]["price_usd"] == 1.5
    assert body["dex"]["market"] is None


def test_market_outage_does_not_break_the_project_list_or_detail(monkeypatch):
    _patch_routes(monkeypatch, boom=True)
    c = TestClient(app)
    r = c.get("/projects")
    assert r.status_code == 200 and all(p["market"] is None for p in r.json())
    d = c.get("/projects/tok")
    assert d.status_code == 200 and d.json()["market"] is None


def test_detail_includes_market_and_contracts(monkeypatch):
    _patch_routes(monkeypatch, market_row=row(contract_address="0xaaa", coingecko_coin_id="some-coin"))
    d = TestClient(app).get("/projects/tok").json()
    assert d["market"]["listed_on_coingecko"] is True and d["contracts"] == ["0xAAA", "0xother"]


def test_detail_for_project_without_contracts_skips_the_lookup(monkeypatch):
    _patch_routes(monkeypatch, market_row=row())
    assert TestClient(app).get("/projects/bare").json()["market"] is None
