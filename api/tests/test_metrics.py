"""
Tests for the rollup-backed metrics layer: aggregation shaping, routes, and
the db-layer pagination that fixes the >1000-score-rows truncation bug.
No live Supabase: fabricated rows, monkeypatched fetchers.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aggregate
import db
from db import get_client
from main import app

USDC = "0x3600000000000000000000000000000000000000"
EURC = "0xbef5f6d51cb62b58e6a8f77868681825c6fe21c1"


@pytest.fixture(autouse=True)
def override_get_client():
    app.dependency_overrides[get_client] = lambda: "dummy-client"
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


# ----------------------------------------------------------- aggregate shaping

def test_network_daily_derived_rates_and_partial_flag():
    rows = [{"day": "2026-10-04", "tx_count": 1000, "failed_tx_count": 25, "usdc_gas_paid": "5.0",
             "contract_creations": 3, "blocks": 500, "token_transfer_count": 800,
             "active_addresses": 90, "source": "live"}]
    out = aggregate.build_network_daily(rows, today="2026-10-04")[0]
    assert out["failed_rate"] == 0.025
    assert out["avg_gas_per_tx_usdc"] == 0.005
    assert out["partial"] is True
    assert aggregate.build_network_daily(rows, today="2026-10-05")[0]["partial"] is False


def test_raw_backfill_days_report_unknowns_as_null_not_zero():
    rows = [{"day": "2026-09-28", "tx_count": 1189555, "failed_tx_count": 0, "usdc_gas_paid": "4912.9499",
             "contract_creations": 0, "blocks": 0, "token_transfer_count": 604202,
             "active_addresses": None, "source": "raw_backfill"}]
    out = aggregate.build_network_daily(rows, today="2026-10-05")[0]
    assert out["failed_tx_count"] is None and out["failed_rate"] is None
    assert out["contract_creations"] is None and out["blocks"] is None
    assert out["tx_count"] == 1189555 and out["usdc_gas_paid"] == pytest.approx(4912.9499)


def test_rates_are_null_when_denominator_is_zero():
    out = aggregate.build_network_daily(
        [{"day": "2026-10-04", "tx_count": 0, "failed_tx_count": 0, "usdc_gas_paid": "0", "source": "live"}],
        today="2026-10-05")[0]
    assert out["failed_rate"] is None and out["avg_gas_per_tx_usdc"] is None


def test_token_daily_symbols_and_avg_transfer_size_stay_per_token():
    rows = [{"day": "2026-10-04", "token_address": USDC, "transfer_count": 4, "volume": "10"},
            {"day": "2026-10-04", "token_address": EURC, "transfer_count": 2, "volume": "9"},
            {"day": "2026-10-04", "token_address": "0x" + "ab" * 20, "transfer_count": 0, "volume": "0"}]
    out = aggregate.build_token_daily(rows)
    assert [o["symbol"] for o in out] == ["USDC", "EURC", None]
    assert out[0]["avg_transfer_size"] == 2.5 and out[2]["avg_transfer_size"] is None


def test_project_summary_tier_and_failed_rate():
    seeded = aggregate.build_project_summary(
        {"id": "usdc", "name": "USDC", "seeded": True},
        {"score": "1", "tx_count_7d": 200, "failed_tx_7d": 10, "computed_at": "t"})
    assert seeded["tier"] == "curated" and seeded["failed_rate_7d"] == 0.05
    discovered = aggregate.build_project_summary({"id": "x", "name": "X", "seeded": False}, None)
    assert discovered["tier"] == "discovered"
    assert discovered["tx_count_7d"] is None and discovered["failed_rate_7d"] is None  # no score -> null, not 0


# --------------------------------------------------------------------- routes

def test_network_daily_route_and_day_validation(client, monkeypatch):
    import routes.metrics as m
    seen = {}
    monkeypatch.setattr(m, "fetch_network_daily",
                        lambda c, days: seen.setdefault("days", days) and [
                            {"day": "2026-10-04", "tx_count": 10, "failed_tx_count": 1, "usdc_gas_paid": "1",
                             "source": "live"}])
    resp = client.get("/metrics/network/daily?days=14")
    assert resp.status_code == 200 and seen["days"] == 14
    assert resp.json()[0]["failed_rate"] == 0.1
    assert client.get("/metrics/network/daily?days=0").status_code == 422
    assert client.get("/metrics/network/daily?days=91").status_code == 422


def test_tokens_daily_resolves_symbol_and_rejects_unknown(client, monkeypatch):
    import routes.metrics as m
    seen = {}

    def fake(c, days, token_address):
        seen["token"] = token_address
        return []

    monkeypatch.setattr(m, "fetch_token_daily", fake)
    assert client.get("/metrics/tokens/daily?token=usdc").status_code == 200
    assert seen["token"] == USDC
    assert client.get(f"/metrics/tokens/daily?token={EURC.upper().replace('0X', '0x')}").status_code == 200
    assert seen["token"] == EURC
    assert client.get("/metrics/tokens/daily").status_code == 200 and seen["token"] is None
    assert client.get("/metrics/tokens/daily?token=DOGE").status_code == 400


def test_contracts_top_route_limits_and_shape(client, monkeypatch):
    import routes.metrics as m
    monkeypatch.setattr(m, "fetch_top_contracts", lambda c, days, limit: [
        {"contract_address": "0xaa", "project_id": "a", "project_name": "Alpha", "category": "dex",
         "tx_count": 80, "failed_tx_count": 8, "usdc_gas": "8", "gas_share": "0.470588"},
        {"contract_address": "0xzz", "project_id": None, "project_name": None, "category": None,
         "tx_count": 5, "failed_tx_count": 0, "usdc_gas": "0.5", "gas_share": "0.029412"}])
    body = client.get("/metrics/contracts/top?days=7&limit=2").json()
    assert body[0]["failed_rate"] == 0.1 and body[0]["gas_share"] == pytest.approx(0.470588)
    assert body[1]["project_id"] is None
    assert client.get("/metrics/contracts/top?limit=101").status_code == 422
    assert client.get("/metrics/contracts/top?days=31").status_code == 422


def test_project_daily_and_score_history_404_for_unknown_project(client, monkeypatch):
    import routes.metrics as m
    monkeypatch.setattr(m, "fetch_project", lambda c, pid: None)
    assert client.get("/projects/nope/daily").status_code == 404
    assert client.get("/scores/nope/history").status_code == 404


def test_project_daily_and_score_history_happy_path(client, monkeypatch):
    import routes.metrics as m
    monkeypatch.setattr(m, "fetch_project", lambda c, pid: {"id": pid})
    monkeypatch.setattr(m, "fetch_project_daily", lambda c, pid, days: [
        {"day": "2026-10-05", "tx_count": 60, "failed_tx_count": 6, "usdc_gas": "6", "unique_users": 2}])
    monkeypatch.setattr(m, "fetch_score_history", lambda c, pid, limit: [
        {"computed_at": "2026-10-05T00:00:00+00:00", "score": "0.9", "tvl_usd": "2", "usdc_gas_7d": "2",
         "unique_users_7d": 2}])
    assert client.get("/projects/a/daily").json()[0]["failed_rate"] == 0.1
    assert client.get("/scores/a/history").json()[0]["score"] == 0.9


# ---------------------------------------------------- db layer: the 1000-row cap

class _Q:
    """Fake PostgREST builder with a hard 1000-row cap and keyset (gt/order/limit) support."""

    def __init__(self, rows, key):
        self.rows, self.key, self.after, self.n = rows, key, None, 1000

    def select(self, *a): return self
    def gt(self, col, val): self.after = val; return self
    def order(self, *a, **k): return self
    def limit(self, n): self.n = min(n, 1000); return self

    def execute(self):
        rows = [r for r in self.rows if self.after is None or r[self.key] > self.after]
        rows.sort(key=lambda r: r[self.key])
        return type("R", (), {"data": rows[: self.n]})()


class _Client:
    def __init__(self, tables): self.tables, self.read = tables, []

    def table(self, name):
        self.read.append(name)
        rows, key = self.tables[name]
        return _Q(rows, key)


def test_fetch_all_latest_scores_reads_the_latest_view_and_pages_past_1000():
    rows = [{"project_id": f"p{i:05d}", "score": "0.1", "computed_at": "t"} for i in range(2300)]
    c = _Client({"latest_project_scores": (rows, "project_id")})
    got = db.fetch_all_latest_scores(c)
    assert len(got) == 2300 and c.read[0] == "latest_project_scores"
    assert len({r["project_id"] for r in got}) == 2300


def test_fetch_projects_pages_past_1000():
    rows = [{"id": f"p{i:05d}", "name": "n"} for i in range(1500)]
    assert len(db.fetch_projects(_Client({"projects": (rows, "id")}))) == 1500
