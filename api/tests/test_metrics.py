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
    monkeypatch.setattr(m, "fetch_pipeline_status", lambda c: {"data_through": "2026-10-04T23:00:00+00:00"})
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


# ------------------------------------------------------------------ freshness

def test_partial_follows_data_through_not_the_calendar():
    rows = [{"day": d, "tx_count": 1, "failed_tx_count": 0, "usdc_gas_paid": "1", "source": "live"}
            for d in ("2026-10-04", "2026-10-05", "2026-10-06")]
    # Today is 10-06 but ingestion has only reached 10-05 10:45: 10-05 is NOT complete.
    out = aggregate.build_network_daily(rows, today="2026-10-06", data_through="2026-10-05T10:45:00+00:00")
    assert [r["partial"] for r in out] == [False, True, True]
    # Fully caught up: only today is partial.
    out = aggregate.build_network_daily(rows, today="2026-10-06", data_through="2026-10-06T09:59:00+00:00")
    assert [r["partial"] for r in out] == [False, False, True]
    # Unknown freshness falls back to the calendar.
    out = aggregate.build_network_daily(rows, today="2026-10-06", data_through=None)
    assert [r["partial"] for r in out] == [False, False, True]


def test_backfill_days_are_never_flagged_partial():
    rows = [{"day": "2026-09-28", "tx_count": 5, "usdc_gas_paid": "1", "source": "raw_backfill"}]
    assert aggregate.build_network_daily(rows, today="2026-10-06",
                                         data_through="2026-09-01T00:00:00+00:00")[0]["partial"] is False


def test_pipeline_status_live_behind_unknown():
    from datetime import datetime, timezone
    now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    live = aggregate.build_pipeline_status({"last_block_number": 7, "data_through": "2026-10-06T11:55:00+00:00"}, now)
    assert live["status"] == "live" and live["lag_seconds"] == 300 and live["last_block_number"] == 7
    behind = aggregate.build_pipeline_status({"data_through": "2026-10-05T10:45:00+00:00"}, now)
    assert behind["status"] == "behind" and behind["lag_seconds"] == 25 * 3600 + 15 * 60
    assert aggregate.build_pipeline_status({"data_through": None}, now)["status"] == "unknown"
    assert aggregate.build_pipeline_status(None, now)["status"] == "unknown"


def test_status_route(client, monkeypatch):
    import routes.metrics as m
    monkeypatch.setattr(m, "fetch_pipeline_status", lambda c: {"last_block_number": 24400000,
                        "data_through": "2026-10-05T10:45:00+00:00", "checkpoint_updated_at": "2026-10-06T10:40:00+00:00"})
    body = client.get("/metrics/status").json()
    assert body["status"] == "behind" and body["last_block_number"] == 24400000
    assert body["data_through"].startswith("2026-10-05T10:45")


def test_network_daily_survives_missing_freshness(client, monkeypatch):
    import routes.metrics as m

    def boom(c):
        raise RuntimeError("pipeline_status function missing")

    monkeypatch.setattr(m, "fetch_pipeline_status", boom)
    monkeypatch.setattr(m, "fetch_network_daily", lambda c, days: [
        {"day": "2026-10-04", "tx_count": 10, "failed_tx_count": 1, "usdc_gas_paid": "1", "source": "live"}])
    assert client.get("/metrics/network/daily").status_code == 200


# ------------------------------------------------------------------- segments

def test_segment_for_maps_every_discovery_category():
    expected = {
        "dex": "defi", "lending": "defi", "yield": "defi", "liquid-staking": "defi",
        "launchpad": "launchpad",
        "infra": "infra", "bridge": "infra", "oracle": "infra", "governance": "infra",
        "stablecoin": "stablecoin", "institutional": "stablecoin",
        "token": "token", "meme": "token", "wrapped": "token",
    }
    for cat, seg in expected.items():
        assert aggregate.segment_for(cat) == seg, cat
    assert aggregate.segment_for("DEX") == "defi"          # case-insensitive
    assert aggregate.segment_for(None) == "other"           # never guessed
    assert aggregate.segment_for("something-new") == "other"


def test_summary_carries_segment():
    s = aggregate.build_project_summary({"id": "r", "name": "R", "category": "dex"}, None)
    assert s["segment"] == "defi"


def test_users_zero_with_transactions_is_not_measured_not_zero():
    # promoted after those days were ingested: has tx but no per-contract sender tracking
    s = aggregate.build_project_summary({"id": "r", "name": "R", "category": "dex"},
                                        {"score": "0.2", "tx_count_7d": 5000, "failed_tx_7d": 1, "unique_users_7d": 0})
    assert s["unique_users_7d"] is None
    # genuinely idle project: no tx and no users -> a real zero is kept
    idle = aggregate.build_project_summary({"id": "i", "name": "I", "category": "dex"},
                                           {"score": "0", "tx_count_7d": 0, "failed_tx_7d": 0, "unique_users_7d": 0})
    assert idle["unique_users_7d"] == 0


# --------------------------------------------------------------- badge safety + ADR-004

def test_badge_escapes_hostile_and_awkward_token_names():
    evil = aggregate.render_badge_svg('</text><script>alert(1)</script>"x', 0.5)
    assert "<script>" not in evil and "&lt;script&gt;" in evil
    amp = aggregate.render_badge_svg("Trump Media & Technology Group C", 0.5)
    assert "&amp;" in amp and " & " not in amp.replace("&amp;", "")
    import xml.dom.minidom
    xml.dom.minidom.parseString(evil)        # still well-formed XML
    xml.dom.minidom.parseString(amp)


def test_badge_unscored_label_for_non_defi_vs_defi_fallback():
    assert "not scored" in aggregate.render_badge_svg("Mars coin", None, unscored_label="not scored")
    assert "insufficient data" in aggregate.render_badge_svg("Some DEX", None)
    assert "0.50" in aggregate.render_badge_svg("Some DEX", 0.5)


def test_badge_route_says_not_scored_for_a_token_but_insufficient_data_for_defi(client, monkeypatch):
    import routes.badge as badge
    monkeypatch.setattr(badge, "fetch_latest_scores_for_project", lambda c, pid: [])
    monkeypatch.setattr(badge, "fetch_project", lambda c, pid: {"id": pid, "name": pid, "category": "meme" if pid == "tok" else "dex"})
    assert "not scored" in client.get("/badge/tok.svg").text
    assert "insufficient data" in client.get("/badge/dx.svg").text
