"""
Tests for compute_scores.py's build_project_metrics() and
compute_all_scores(). Uses fabricated projects/gas_events/token_flows rows
(no live RPC or DB) to verify the wiring between raw Supabase rows and
tvl.py/scoring.py is correct — same intent as ingestion/tests/test_worker.py.
"""

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compute_scores import build_project_metrics, compute_all_scores

NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)
CONTRACT_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
USER_1 = "0xcccccccccccccccccccccccccccccccccccccccc"
USER_2 = "0xddddddddddddddddddddddddddddddddddddddd0"
USDC = "0x3600000000000000000000000000000000000000"


def test_build_project_metrics_wires_gas_users_tvl_age():
    projects = [{
        "id": "my-project",
        "contracts": [CONTRACT_A],
        "created_at": (NOW - timedelta(days=15)).isoformat(),
    }]
    gas_events_7d = [
        {"project_id": "my-project", "usdc_gas_paid": "1.5"},
        {"project_id": "my-project", "usdc_gas_paid": "0.5"},
    ]
    token_flows_7d = [
        {"token_address": USDC, "from_address": USER_1, "to_address": CONTRACT_A, "amount": "10"},
        {"token_address": USDC, "from_address": USER_2, "to_address": CONTRACT_A, "amount": "5"},
        {"token_address": USDC, "from_address": USER_1, "to_address": CONTRACT_A, "amount": "1"},  # dup sender
    ]
    all_token_flows = token_flows_7d  # same flows also make up all-time history here

    metrics = build_project_metrics(projects, gas_events_7d, token_flows_7d, all_token_flows, NOW)

    m = metrics["my-project"]
    assert m["usdc_gas_7d"] == Decimal("2.0")
    assert m["unique_users_7d"] == Decimal("2")  # USER_1, USER_2 — dup collapsed
    assert m["tvl_usd"] == Decimal("16")  # 10 + 5 + 1
    assert m["age_bonus"] == Decimal("0.5")  # 15 of 30 days


def test_build_project_metrics_project_with_no_activity_is_all_zero():
    projects = [{"id": "quiet-project", "contracts": [CONTRACT_A], "created_at": NOW.isoformat()}]
    metrics = build_project_metrics(projects, [], [], [], NOW)
    m = metrics["quiet-project"]
    assert m["usdc_gas_7d"] == Decimal("0")
    assert m["unique_users_7d"] == Decimal("0")
    assert m["tvl_usd"] == Decimal("0")
    assert m["age_bonus"] == Decimal("0")


def test_build_project_metrics_ignores_unrelated_projects_gas():
    projects = [
        {"id": "a", "contracts": [CONTRACT_A], "created_at": NOW.isoformat()},
        {"id": "b", "contracts": ["0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"], "created_at": NOW.isoformat()},
    ]
    gas_events_7d = [{"project_id": "a", "usdc_gas_paid": "100"}]
    metrics = build_project_metrics(projects, gas_events_7d, [], [], NOW)
    assert metrics["a"]["usdc_gas_7d"] == Decimal("100")
    assert metrics["b"]["usdc_gas_7d"] == Decimal("0")


def test_compute_all_scores_produces_one_row_per_project_with_expected_fields():
    metrics = {
        "a": {
            "usdc_gas_7d": Decimal("10"),
            "unique_users_7d": Decimal("2"),
            "tvl_usd": Decimal("100"),
            "age_bonus": Decimal("1"),
        },
        "b": {
            "usdc_gas_7d": Decimal("0"),
            "unique_users_7d": Decimal("0"),
            "tvl_usd": Decimal("0"),
            "age_bonus": Decimal("0"),
        },
    }
    rows = compute_all_scores(metrics, NOW)
    by_id = {r["project_id"]: r for r in rows}

    assert len(rows) == 2
    assert Decimal(by_id["a"]["score"]) == Decimal("1")
    assert Decimal(by_id["b"]["score"]) == Decimal("0")
    assert by_id["a"]["computed_at"] == NOW.isoformat()
    assert by_id["a"]["unique_users_7d"] == 2
    assert isinstance(by_id["a"]["unique_users_7d"], int)
