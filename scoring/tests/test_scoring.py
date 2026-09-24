"""
Tests for scoring.py. Per docs/TESTING.md #3, must confirm: the formula
matches docs/SCHEMA.md, and near-empty input (0 or 1 project, all-zero/tied
metrics) doesn't crash and doesn't produce a misleading fabricated score
(docs/BUGS.md #3).
"""

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scoring import (
    AGE_BONUS_CAP_DAYS,
    compute_score,
    contract_age_bonus,
    normalize,
)


def test_normalize_basic_range():
    values = [Decimal("0"), Decimal("50"), Decimal("100")]
    assert normalize(Decimal("50"), values) == Decimal("0.5")
    assert normalize(Decimal("0"), values) == Decimal("0")
    assert normalize(Decimal("100"), values) == Decimal("1")


def test_normalize_empty_returns_zero_not_error():
    assert normalize(Decimal("5"), []) == Decimal("0")


def test_normalize_all_tied_returns_zero_not_arbitrary_midpoint():
    # Single project, or every project equal on this metric: no relative
    # signal exists yet, so this must not fabricate a 0.5 "average" score.
    values = [Decimal("10")]
    assert normalize(Decimal("10"), values) == Decimal("0")
    values_tied = [Decimal("7"), Decimal("7"), Decimal("7")]
    assert normalize(Decimal("7"), values_tied) == Decimal("0")


def test_contract_age_bonus_zero_at_deployment():
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    assert contract_age_bonus(now, now) == Decimal("0")


def test_contract_age_bonus_full_at_cap():
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    created = now - timedelta(days=AGE_BONUS_CAP_DAYS)
    assert contract_age_bonus(created, now) == Decimal("1")


def test_contract_age_bonus_ramps_linearly_partway():
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    created = now - timedelta(days=AGE_BONUS_CAP_DAYS / 2)
    assert contract_age_bonus(created, now) == Decimal("0.5")


def test_contract_age_bonus_clamped_above_cap():
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    created = now - timedelta(days=AGE_BONUS_CAP_DAYS * 3)
    assert contract_age_bonus(created, now) == Decimal("1")


def test_contract_age_bonus_handles_naive_datetimes():
    # created_at pulled from Postgres can come back naive; must not crash.
    now = datetime(2026, 9, 22)
    created = now - timedelta(days=AGE_BONUS_CAP_DAYS)
    assert contract_age_bonus(created, now) == Decimal("1")


def test_compute_score_equal_weights_sum_correctly():
    # Two projects, one strictly ahead on every metric — its score must be
    # strictly higher, and a project maxed on everything scores 1.0.
    score_leader = compute_score(
        usdc_gas_7d=Decimal("100"),
        all_usdc_gas_7d=[Decimal("100"), Decimal("0")],
        unique_users_7d=Decimal("10"),
        all_unique_users_7d=[Decimal("10"), Decimal("0")],
        tvl_usd=Decimal("1000"),
        all_tvl_usd=[Decimal("1000"), Decimal("0")],
        age_bonus=Decimal("1"),
    )
    assert score_leader == Decimal("1")

    score_trailing = compute_score(
        usdc_gas_7d=Decimal("0"),
        all_usdc_gas_7d=[Decimal("100"), Decimal("0")],
        unique_users_7d=Decimal("0"),
        all_unique_users_7d=[Decimal("10"), Decimal("0")],
        tvl_usd=Decimal("0"),
        all_tvl_usd=[Decimal("1000"), Decimal("0")],
        age_bonus=Decimal("0"),
    )
    assert score_trailing == Decimal("0")


def test_compute_score_single_project_no_crash_no_fabricated_ranking():
    # Sparse-data case: one tracked project, nothing to compare against.
    # Only the age bonus can contribute a nonzero term.
    score = compute_score(
        usdc_gas_7d=Decimal("5"),
        all_usdc_gas_7d=[Decimal("5")],
        unique_users_7d=Decimal("2"),
        all_unique_users_7d=[Decimal("2")],
        tvl_usd=Decimal("50"),
        all_tvl_usd=[Decimal("50")],
        age_bonus=Decimal("0.5"),
    )
    assert score == Decimal("0.125")  # only 0.25 * 0.5 (age) survives
