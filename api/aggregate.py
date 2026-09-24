"""
aggregate.py — pure data-shaping logic for the API layer.

Kept separate from db.py (network calls) and routes/ (FastAPI wiring) so it's
unit-testable with fabricated rows, same pattern as scoring/compute_scores.py
and ingestion/worker.py's process_block().

project_scores has one row per project per computation run (see
docs/SCHEMA.md) — everything here works from "the latest row per project,"
never an average or a sum across runs.
"""

from decimal import Decimal, InvalidOperation
from typing import Optional


def latest_score_by_project(score_rows: list[dict]) -> dict[str, dict]:
    """
    Given raw project_scores rows (possibly many computation runs per
    project), return {project_id: latest_row}. Rows are compared by
    computed_at (ISO string comparison works since all timestamps are UTC
    and the same format from Postgres).
    """
    latest: dict[str, dict] = {}
    for row in score_rows:
        project_id = row["project_id"]
        current = latest.get(project_id)
        if current is None or row["computed_at"] > current["computed_at"]:
            latest[project_id] = row
    return latest


def _to_float(value) -> Optional[float]:
    """Best-effort numeric coercion. None/unparsable input -> None, never a crash."""
    if value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def build_project_summary(project: dict, score_row: Optional[dict]) -> dict:
    """
    Merge a `projects` row with its latest `project_scores` row (if any) into
    one API-facing dict. A project with no score yet (brand new, or the
    scoring job hasn't run since it was added) gets explicit nulls, never a
    fabricated zero that would look like a real "no activity" measurement
    (see docs/BUGS.md #3).
    """
    return {
        "id": project["id"],
        "name": project["name"],
        "category": project.get("category"),
        "score": _to_float(score_row["score"]) if score_row else None,
        "tvl_usd": _to_float(score_row.get("tvl_usd")) if score_row else None,
        "usdc_gas_7d": _to_float(score_row.get("usdc_gas_7d")) if score_row else None,
        "unique_users_7d": score_row.get("unique_users_7d") if score_row else None,
        "computed_at": score_row.get("computed_at") if score_row else None,
    }


def build_all_summaries(projects: list[dict], score_rows: list[dict]) -> list[dict]:
    """Build a project summary for every tracked project, scored or not."""
    latest = latest_score_by_project(score_rows)
    return [build_project_summary(p, latest.get(p["id"])) for p in projects]


def top_by_metric(summaries: list[dict], metric: str, limit: int) -> list[dict]:
    """
    Rank summaries by `metric` descending, treating a null value (no score
    yet) as excluded rather than as zero — an unscored project competing at
    the bottom of a leaderboard by fiat would misrepresent "no data" as "no
    activity."
    """
    scored = [s for s in summaries if s.get(metric) is not None]
    scored.sort(key=lambda s: s[metric], reverse=True)
    return scored[:limit]


def build_network_summary(projects: list[dict], score_rows: list[dict], network_stats_row: Optional[dict]) -> dict:
    """
    Network-wide stat-strip data (docs/BRANDING.md §5). total_projects and
    total_scored come from the same project/score data every other route
    already reads; total_tvl_usd is a simple sum across current latest
    scores (no new pipeline data needed — TVL is already per-project).
    total_volume_7d / total_tx_7d / total_unique_users_7d come from
    network_stats (see db.fetch_network_stats), which IS new pipeline
    output — None on every one of those fields if the scoring job hasn't
    run yet, never a fabricated 0 (docs/BUGS.md #3).
    """
    summaries = build_all_summaries(projects, score_rows)
    total_scored = sum(1 for s in summaries if s["score"] is not None)
    tvl_values = [s["tvl_usd"] for s in summaries if s["tvl_usd"] is not None]
    total_tvl_usd = sum(tvl_values) if tvl_values else None

    return {
        "total_projects": len(projects),
        "total_scored": total_scored,
        "total_tvl_usd": total_tvl_usd,
        "total_volume_7d": _to_float(network_stats_row["total_volume_7d"]) if network_stats_row else None,
        "total_tx_7d": network_stats_row.get("total_tx_7d") if network_stats_row else None,
        "total_unique_users_7d": network_stats_row.get("total_unique_users_7d") if network_stats_row else None,
        "computed_at": network_stats_row.get("computed_at") if network_stats_row else None,
    }


def render_badge_svg(project_name: str, score: Optional[float]) -> str:
    """
    Render a minimal shields.io-style SVG badge. Falls back to an honest
    "insufficient data" label rather than a fabricated 0.0-looking score
    when a project has no computed score yet (docs/AUDIT.md badge fallback
    requirement, docs/BUGS.md #3).
    """
    label = project_name
    value = f"{score:.2f}" if score is not None else "insufficient data"
    color = "#5FC9C0" if score is not None else "#8f8d86"  # Isogram verdigris / ink-dim

    label_width = 10 + 7 * len(label)
    value_width = 10 + 7 * len(value)
    total_width = label_width + value_width

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" role="img" aria-label="{label}: {value}">
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_width}" height="20" fill="#101012"/>
    <rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#f2f0ea" text-anchor="middle" font-family="Verdana,Geneva,sans-serif" font-size="11">
    <text x="{label_width / 2}" y="14">{label}</text>
    <text x="{label_width + value_width / 2}" y="14">{value}</text>
  </g>
</svg>"""
