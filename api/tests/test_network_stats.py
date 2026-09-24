"""
Tests for compute_scores.py's build_network_stats(). Pure function, no DB —
same intent as test_compute_scores.py's tests for build_project_metrics().
"""

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compute_scores import build_network_stats

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)
USDC = "0x3600000000000000000000000000000000000000"
UNPRICED_TOKEN = "0x000000000000000000000000000000000dead1"
USER_1 = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
USER_2 = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def test_build_network_stats_sums_priced_volume_only():
    token_flows = [
        {"token_address": USDC, "from_address": USER_1, "to_address": "0xc", "amount": "100", "usd_value": "100"},
        {"token_address": UNPRICED_TOKEN, "from_address": USER_2, "to_address": "0xd", "amount": "9999", "usd_value": None},
    ]
    stats = build_network_stats([], token_flows, NOW)
    assert stats["total_volume_7d"] == "100"  # unpriced token's raw amount never enters the USD total


def test_build_network_stats_counts_transactions():
    gas_events = [{"tx_hash": "0x1"}, {"tx_hash": "0x2"}, {"tx_hash": "0x3"}]
    stats = build_network_stats(gas_events, [], NOW)
    assert stats["total_tx_7d"] == 3


def test_build_network_stats_dedupes_unique_users_network_wide():
    token_flows = [
        {"token_address": USDC, "from_address": USER_1, "to_address": "0xc", "amount": "1", "usd_value": "1"},
        {"token_address": USDC, "from_address": USER_1, "to_address": "0xd", "amount": "2", "usd_value": "2"},  # same sender, different target
        {"token_address": USDC, "from_address": USER_2, "to_address": "0xc", "amount": "3", "usd_value": "3"},
    ]
    stats = build_network_stats([], token_flows, NOW)
    assert stats["total_unique_users_7d"] == 2


def test_build_network_stats_empty_input_is_zero_not_error():
    stats = build_network_stats([], [], NOW)
    assert stats["total_volume_7d"] == "0"
    assert stats["total_tx_7d"] == 0
    assert stats["total_unique_users_7d"] == 0
    assert stats["computed_at"] == NOW.isoformat()


def test_build_network_stats_includes_activity_regardless_of_project_tracking():
    # No project_id needed anywhere here — network_stats reflects chain-wide
    # activity independent of which contracts are identified as projects.
    gas_events = [{"tx_hash": "0x1", "project_id": None}]
    token_flows = [{"token_address": USDC, "from_address": USER_1, "to_address": "0xunknown", "amount": "5", "usd_value": "5"}]
    stats = build_network_stats(gas_events, token_flows, NOW)
    assert stats["total_tx_7d"] == 1
    assert stats["total_volume_7d"] == "5"
