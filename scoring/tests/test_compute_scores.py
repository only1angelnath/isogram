"""
Tests for compute_scores.py - wiring between the rollup-backed window metrics,
live TVL (injected, no network) and scoring.py. Rewritten 2026-10-04: the
previous version tested the pre-rollup signatures (gas_events/token_flows
rows) and had already gone stale after the on-chain TVL rewrite.
"""

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import compute_scores
from compute_scores import (
    build_network_stats,
    build_project_metrics,
    compute_all_scores,
    index_window_metrics,
)

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
CONTRACT_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
CONTRACT_B = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def fake_tvl(pool, contracts):
    # deterministic stand-in for the on-chain query: 16 USD per contract
    return Decimal(16) * len(list(contracts))


def test_index_window_metrics_keeps_exact_decimal_from_text():
    rows = [{"project_id": "p", "tx_count": 17, "failed_tx_count": 1,
             "usdc_gas": "2.123456789012345678", "unique_users": 3}]
    m = index_window_metrics(rows)["p"]
    assert m["usdc_gas"] == Decimal("2.123456789012345678")  # no float rounding
    assert m["unique_users"] == Decimal(3) and m["tx_count"] == 17 and m["failed_tx_count"] == 1


def test_build_project_metrics_wires_gas_users_tvl_age_and_activity():
    projects = [{"id": "my-project", "contracts": [CONTRACT_A.upper()],
                 "created_at": (NOW - timedelta(days=15)).isoformat()}]
    wm = index_window_metrics([{"project_id": "my-project", "tx_count": 40, "failed_tx_count": 4,
                                "usdc_gas": "2.0", "unique_users": 2}])
    m = build_project_metrics(projects, wm, [], NOW, tvl_fetcher=fake_tvl)["my-project"]
    assert m["usdc_gas_7d"] == Decimal("2.0")
    assert m["unique_users_7d"] == Decimal(2)
    assert m["tvl_usd"] == Decimal(16)
    assert m["age_bonus"] == Decimal("0.5")  # 15 of 30 days
    assert m["tx_count_7d"] == 40 and m["failed_tx_7d"] == 4


def test_project_missing_from_window_is_all_zero_not_missing():
    projects = [{"id": "quiet", "contracts": [CONTRACT_A], "created_at": NOW.isoformat()}]
    m = build_project_metrics(projects, {}, [], NOW, tvl_fetcher=lambda p, c: Decimal(0))["quiet"]
    assert m["usdc_gas_7d"] == 0 and m["unique_users_7d"] == 0 and m["tvl_usd"] == 0
    assert m["age_bonus"] == 0 and m["tx_count_7d"] == 0 and m["failed_tx_7d"] == 0


def test_other_projects_activity_does_not_leak():
    projects = [{"id": "a", "contracts": [CONTRACT_A], "created_at": NOW.isoformat()},
                {"id": "b", "contracts": [CONTRACT_B], "created_at": NOW.isoformat()}]
    wm = index_window_metrics([{"project_id": "a", "tx_count": 1, "failed_tx_count": 0,
                                "usdc_gas": "100", "unique_users": 1}])
    metrics = build_project_metrics(projects, wm, [], NOW, tvl_fetcher=fake_tvl)
    assert metrics["a"]["usdc_gas_7d"] == 100 and metrics["b"]["usdc_gas_7d"] == 0


def test_compute_all_scores_one_row_per_project_with_expected_fields():
    metrics = {
        "a": {"usdc_gas_7d": Decimal(10), "unique_users_7d": Decimal(2), "tvl_usd": Decimal(100),
              "age_bonus": Decimal(1), "tx_count_7d": 9, "failed_tx_7d": 1},
        "b": {"usdc_gas_7d": Decimal(0), "unique_users_7d": Decimal(0), "tvl_usd": Decimal(0),
              "age_bonus": Decimal(0), "tx_count_7d": 0, "failed_tx_7d": 0},
    }
    rows = {r["project_id"]: r for r in compute_all_scores(metrics, NOW)}
    assert len(rows) == 2
    assert Decimal(rows["a"]["score"]) == 1 and Decimal(rows["b"]["score"]) == 0
    assert rows["a"]["computed_at"] == NOW.isoformat()
    assert isinstance(rows["a"]["unique_users_7d"], int) and rows["a"]["unique_users_7d"] == 2
    assert rows["a"]["tx_count_7d"] == 9 and rows["a"]["failed_tx_7d"] == 1


def test_activity_columns_do_not_change_the_score():
    base = {"usdc_gas_7d": Decimal(5), "unique_users_7d": Decimal(1), "tvl_usd": Decimal(5), "age_bonus": Decimal(0)}
    other = {"usdc_gas_7d": Decimal(1), "unique_users_7d": Decimal(1), "tvl_usd": Decimal(1), "age_bonus": Decimal(0)}
    r1 = compute_all_scores({"x": {**base, "tx_count_7d": 1, "failed_tx_7d": 0}, "y": {**other, "tx_count_7d": 1, "failed_tx_7d": 0}}, NOW)
    r2 = compute_all_scores({"x": {**base, "tx_count_7d": 999, "failed_tx_7d": 500}, "y": {**other, "tx_count_7d": 1, "failed_tx_7d": 0}}, NOW)
    assert [r["score"] for r in r1] == [r["score"] for r in r2]


def test_build_network_stats_shapes_and_exact_decimal():
    s = build_network_stats({"total_tx": 150, "total_volume_usd": "15.000001", "unique_users": 3, "days_with_data": 2}, NOW)
    assert s == {"total_volume_7d": "15.000001", "total_tx_7d": 150, "total_unique_users_7d": 3,
                 "computed_at": NOW.isoformat()}


# ---------------------------------------------------------------- run()

class _Exec:
    def __init__(self, data=None):
        self.data = data

    def execute(self):
        return self


class _Table:
    def __init__(self, client, name):
        self.client, self.name = client, name

    def select(self, *a, **k): return self
    def gt(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def execute(self):
        assert self.name == "projects", f"scoring must not read {self.name}"
        return type("R", (), {"data": self.client.projects})()

    def upsert(self, row):
        self.client.writes.append(("network_stats", row)); return _Exec()

    def insert(self, rows):
        self.client.writes.append((self.name, rows)); return _Exec()


class _FakeClient:
    def __init__(self):
        self.projects = [{"id": "a", "contracts": [CONTRACT_A], "created_at": "2026-09-20T00:00:00+00:00"},
                         {"id": "idle", "contracts": [CONTRACT_B], "created_at": "2026-09-20T00:00:00+00:00"}]
        self.writes, self.rpcs = [], []

    def table(self, name): return _Table(self, name)

    def rpc(self, fn, params):
        self.rpcs.append((fn, params))
        data = {
            "network_window_stats": [{"total_tx": 100, "total_volume_usd": "15.0", "unique_users": 3, "days_with_data": 2}],
            "project_window_metrics": [{"project_id": "a", "tx_count": 10, "failed_tx_count": 1,
                                        "usdc_gas": "4.5", "unique_users": 2}],
        }[fn]
        return _Exec(data)


def test_run_reads_only_rollups_and_writes_scores(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(compute_scores, "get_client", lambda: client)
    monkeypatch.setattr(compute_scores, "get_web3_pool", lambda: [object()])
    monkeypatch.setattr(compute_scores, "fetch_project_tvl_onchain", lambda pool, contracts: Decimal(1))
    compute_scores.run()
    assert [fn for fn, _ in client.rpcs] == ["network_window_stats", "project_window_metrics"]
    assert all(p == {"p_days": 7} for _, p in client.rpcs)
    names = [n for n, _ in client.writes]
    assert names == ["network_stats", "project_scores"]
    scores = {r["project_id"]: r for r in client.writes[1][1]}
    assert set(scores) == {"a", "idle"}  # idle project still scored (as zero), not dropped
    assert scores["a"]["tx_count_7d"] == 10 and scores["idle"]["tx_count_7d"] == 0
