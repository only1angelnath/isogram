"""
compute_scores.py — main scoring job entrypoint.

Run periodically (GitHub Actions cron, less frequent than ingestion — see
docs/ARCHITECTURE.md §2.4). Each run:
  1. Reads all tracked projects.
  2. Reads gas_events and token_flows for the trailing 7 days (usdc_gas_7d,
     unique_users_7d) and all-time token_flows (for TVL).
  3. Computes each project's raw metrics, normalizes them relative to each
     other, and combines them into one score (scoring.py).
  4. Writes one project_scores row per project for this run.

Usage:
    python compute_scores.py
"""

import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()

from db import (
    fetch_all_token_flows,
    fetch_gas_events_since,
    fetch_projects,
    fetch_token_flows_since,
    get_client,
    upsert_project_scores,
)
from scoring import compute_score, contract_age_bonus
from tvl import calculate_project_tvl

SCORE_WINDOW_DAYS = 7


def _parse_ts(value) -> datetime:
    """Parse a Postgres/Supabase timestamptz string into an aware datetime."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def build_project_metrics(
    projects: list[dict],
    gas_events_7d: list[dict],
    token_flows_7d: list[dict],
    all_token_flows: list[dict],
    now: datetime,
) -> dict[str, dict]:
    """
    Pure function: turn raw rows into a {project_id: {metric: value}} dict.
    Kept separate from the network calls in run() so it's unit-testable
    without a live database.
    """
    gas_by_project: dict[str, Decimal] = {}
    for row in gas_events_7d:
        project_id = row.get("project_id")
        if not project_id:
            continue
        gas_by_project[project_id] = gas_by_project.get(project_id, Decimal("0")) + Decimal(
            str(row["usdc_gas_paid"])
        )

    metrics: dict[str, dict] = {}
    for project in projects:
        project_id = project["id"]
        contracts = [c.lower() for c in (project.get("contracts") or [])]
        contracts_set = set(contracts)

        usdc_gas_7d = gas_by_project.get(project_id, Decimal("0"))

        # unique_users_7d: distinct senders in token_flows targeting this
        # project's contracts in the trailing window. See
        # docs/decisions/ADR-002-scoring-formula.md for why this is the
        # chosen proxy (gas_events has no sender/from column).
        senders = {
            (flow.get("from_address") or "").lower()
            for flow in token_flows_7d
            if (flow.get("to_address") or "").lower() in contracts_set
            and flow.get("from_address")
        }
        unique_users_7d = Decimal(len(senders))

        tvl_usd = calculate_project_tvl(all_token_flows, contracts)

        created_at = _parse_ts(project["created_at"]) if project.get("created_at") else now
        age_bonus = contract_age_bonus(created_at, now)

        metrics[project_id] = {
            "usdc_gas_7d": usdc_gas_7d,
            "unique_users_7d": unique_users_7d,
            "tvl_usd": tvl_usd,
            "age_bonus": age_bonus,
        }
    return metrics


def compute_all_scores(metrics: dict[str, dict], computed_at: datetime) -> list[dict]:
    """
    Pure function: given per-project raw metrics, normalize across the whole
    set and compute each project's final score. Returns project_scores rows
    ready to insert.
    """
    all_gas = [m["usdc_gas_7d"] for m in metrics.values()]
    all_users = [m["unique_users_7d"] for m in metrics.values()]
    all_tvl = [m["tvl_usd"] for m in metrics.values()]

    rows = []
    for project_id, m in metrics.items():
        score = compute_score(
            usdc_gas_7d=m["usdc_gas_7d"],
            all_usdc_gas_7d=all_gas,
            unique_users_7d=m["unique_users_7d"],
            all_unique_users_7d=all_users,
            tvl_usd=m["tvl_usd"],
            all_tvl_usd=all_tvl,
            age_bonus=m["age_bonus"],
        )
        rows.append({
            "project_id": project_id,
            "score": str(score),
            "tvl_usd": str(m["tvl_usd"]),
            "usdc_gas_7d": str(m["usdc_gas_7d"]),
            "unique_users_7d": int(m["unique_users_7d"]),
            "computed_at": computed_at.isoformat(),
        })
    return rows


def run():
    client = get_client()
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=SCORE_WINDOW_DAYS)).isoformat()

    projects = fetch_projects(client)
    if not projects:
        print("No tracked projects yet. Nothing to score.")
        return

    gas_events_7d = fetch_gas_events_since(client, since)
    token_flows_7d = fetch_token_flows_since(client, since)
    all_token_flows = fetch_all_token_flows(client)

    metrics = build_project_metrics(projects, gas_events_7d, token_flows_7d, all_token_flows, now)
    rows = compute_all_scores(metrics, now)

    upsert_project_scores(client, rows)
    print(f"Wrote {len(rows)} project_scores rows for computed_at={now.isoformat()}.")


if __name__ == "__main__":
    start = time.monotonic()
    try:
        run()
    except Exception as exc:
        print(f"Scoring run failed: {exc}", file=sys.stderr)
        raise
    print(f"Finished in {time.monotonic() - start:.1f}s")
