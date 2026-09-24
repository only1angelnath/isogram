"""
Tests for aggregate.py. Covers latest-score dedup, null-vs-zero handling for
unscored projects (docs/BUGS.md #3), leaderboard ranking, and the badge SVG
fallback (docs/TESTING.md #4).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aggregate import (
    build_all_summaries,
    build_network_summary,
    build_project_summary,
    latest_score_by_project,
    render_badge_svg,
    top_by_metric,
)


def _score(project_id, computed_at, score="0.5", tvl_usd="100", usdc_gas_7d="1", unique_users_7d=2):
    return {
        "project_id": project_id,
        "score": score,
        "tvl_usd": tvl_usd,
        "usdc_gas_7d": usdc_gas_7d,
        "unique_users_7d": unique_users_7d,
        "computed_at": computed_at,
    }


def test_latest_score_by_project_picks_most_recent():
    rows = [
        _score("a", "2026-09-20T00:00:00+00:00", score="0.1"),
        _score("a", "2026-09-22T00:00:00+00:00", score="0.9"),
        _score("b", "2026-09-21T00:00:00+00:00", score="0.5"),
    ]
    latest = latest_score_by_project(rows)
    assert latest["a"]["score"] == "0.9"
    assert latest["b"]["score"] == "0.5"


def test_latest_score_by_project_empty_input():
    assert latest_score_by_project([]) == {}


def test_build_project_summary_with_score():
    project = {"id": "a", "name": "Project A", "category": "dex"}
    score_row = _score("a", "2026-09-22T00:00:00+00:00", score="0.75", tvl_usd="1000")
    summary = build_project_summary(project, score_row)
    assert summary["score"] == 0.75
    assert summary["tvl_usd"] == 1000.0
    assert summary["computed_at"] == "2026-09-22T00:00:00+00:00"


def test_build_project_summary_without_score_is_null_not_zero():
    # A project with no project_scores row yet must not look like a project
    # that scored zero — those are different facts (docs/BUGS.md #3).
    project = {"id": "brand-new", "name": "Brand New", "category": "infra"}
    summary = build_project_summary(project, None)
    assert summary["score"] is None
    assert summary["tvl_usd"] is None
    assert summary["usdc_gas_7d"] is None
    assert summary["unique_users_7d"] is None
    assert summary["computed_at"] is None


def test_build_all_summaries_mixed_scored_and_unscored():
    projects = [
        {"id": "a", "name": "A", "category": "dex"},
        {"id": "b", "name": "B", "category": "infra"},
    ]
    scores = [_score("a", "2026-09-22T00:00:00+00:00", score="0.5")]
    summaries = build_all_summaries(projects, scores)
    by_id = {s["id"]: s for s in summaries}
    assert by_id["a"]["score"] == 0.5
    assert by_id["b"]["score"] is None


def test_top_by_metric_sorts_descending_and_excludes_unscored():
    summaries = [
        {"id": "a", "score": 0.2},
        {"id": "b", "score": 0.9},
        {"id": "c", "score": None},  # no data yet — must not sort as 0 or last-but-visible
    ]
    top = top_by_metric(summaries, "score", limit=10)
    assert [s["id"] for s in top] == ["b", "a"]


def test_top_by_metric_respects_limit():
    summaries = [{"id": str(i), "score": float(i)} for i in range(5)]
    top = top_by_metric(summaries, "score", limit=2)
    assert len(top) == 2
    assert top[0]["id"] == "4"
    assert top[1]["id"] == "3"


def test_render_badge_svg_with_score():
    svg = render_badge_svg("Isogram", 0.87)
    assert svg.startswith("<svg")
    assert "0.87" in svg
    assert "Isogram" in svg


def test_render_badge_svg_no_score_falls_back_honestly():
    # Must not render "0.00" for a project that hasn't been scored yet —
    # that would look like a real, bad score rather than missing data.
    svg = render_badge_svg("Brand New Project", None)
    assert "insufficient data" in svg
    assert "0.00" not in svg


def test_build_network_summary_with_full_data():
    projects = [
        {"id": "a", "name": "A", "category": "dex"},
        {"id": "b", "name": "B", "category": "infra"},
    ]
    scores = [
        _score("a", "2026-09-24T00:00:00+00:00", score="0.5", tvl_usd="100"),
        _score("b", "2026-09-24T00:00:00+00:00", score="0.8", tvl_usd="50"),
    ]
    network_stats_row = {
        "total_volume_7d": "1234.5",
        "total_tx_7d": 42,
        "total_unique_users_7d": 7,
        "computed_at": "2026-09-24T00:00:00+00:00",
    }
    summary = build_network_summary(projects, scores, network_stats_row)

    assert summary["total_projects"] == 2
    assert summary["total_scored"] == 2
    assert summary["total_tvl_usd"] == 150.0  # summed across both projects
    assert summary["total_volume_7d"] == 1234.5
    assert summary["total_tx_7d"] == 42
    assert summary["total_unique_users_7d"] == 7


def test_build_network_summary_no_network_stats_row_yet_is_null_not_zero():
    # Scoring job hasn't run since network_stats was added — must not show
    # a fabricated 0 for volume/tx/users (docs/BUGS.md #3), even though
    # total_projects/total_scored are still real (they come from data that
    # already exists independent of network_stats).
    projects = [{"id": "a", "name": "A", "category": "dex"}]
    scores = [_score("a", "2026-09-24T00:00:00+00:00", score="0.5", tvl_usd="100")]
    summary = build_network_summary(projects, scores, None)

    assert summary["total_projects"] == 1
    assert summary["total_scored"] == 1
    assert summary["total_tvl_usd"] == 100.0
    assert summary["total_volume_7d"] is None
    assert summary["total_tx_7d"] is None
    assert summary["total_unique_users_7d"] is None


def test_build_network_summary_unscored_project_excluded_from_tvl_sum():
    projects = [
        {"id": "a", "name": "A", "category": "dex"},
        {"id": "quiet", "name": "Quiet", "category": "infra"},
    ]
    scores = [_score("a", "2026-09-24T00:00:00+00:00", score="0.5", tvl_usd="100")]
    summary = build_network_summary(projects, scores, None)

    assert summary["total_projects"] == 2
    assert summary["total_scored"] == 1
    assert summary["total_tvl_usd"] == 100.0  # quiet's null TVL doesn't zero out the sum
