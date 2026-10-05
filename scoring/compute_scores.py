"""
compute_scores.py — main scoring job entrypoint.

Run periodically (GitHub Actions cron, less frequent than ingestion — see
docs/ARCHITECTURE.md §2.4). Each run:
  1. Reads network-wide window totals and per-project window metrics from the
     DAILY ROLLUPS (daily_*_metrics / daily_contract_users) through Postgres
     functions — see docs/decisions/ADR-003-rollup-metrics-source.md. Before
     2026-10-04 this paged ~1M raw gas_events/token_flows rows through
     PostgREST (679s, crashed twice on statement timeouts); per-transaction
     rows no longer exist.
  2. Queries each project's CURRENT on-chain token balances for TVL (tvl.py).
  3. Normalizes the metrics relative to each other and combines them into one
     score (scoring.py — formula UNCHANGED, see ADR-002).
  4. Writes network_stats and one project_scores row per project.

Usage:
    python compute_scores.py
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()

from db import (
    fetch_network_window_stats,
    fetch_project_window_metrics,
    fetch_projects,
    get_client,
    upsert_network_stats,
    upsert_project_scores,
)
from scoring import compute_score, contract_age_bonus
from tvl import fetch_project_tvl_onchain, get_web3_pool

SCORE_WINDOW_DAYS = 7

# Raw-row retention pruning was removed 2026-10-04: there are no raw rows any more
# (ingestion writes rollups only). Rollup housekeeping lives in ingestion/rollup.py.



def _parse_ts(value) -> datetime:
    """Parse a Postgres/Supabase timestamptz string into an aware datetime."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def index_window_metrics(rows: list[dict]) -> dict[str, dict]:
    """
    Pure function: project_window_metrics() rows -> {project_id: metrics} with
    exact Decimals (usdc_gas arrives as TEXT on purpose - never a float).
    """
    out: dict[str, dict] = {}
    for row in rows:
        out[row["project_id"]] = {
            "usdc_gas": Decimal(str(row["usdc_gas"])),
            "unique_users": Decimal(int(row["unique_users"])),
            "tx_count": int(row["tx_count"]),
            "failed_tx_count": int(row["failed_tx_count"]),
        }
    return out


def build_project_metrics(
    projects: list[dict],
    window_metrics: dict[str, dict],
    rpc_pool: list,
    now: datetime,
    tvl_fetcher=None,
) -> dict[str, dict]:
    """
    Turn per-project window metrics (from the rollups) + live on-chain TVL
    into {project_id: {metric: value}}. A project with no activity in the
    window is all-zero, never missing. Only the TVL step makes network calls
    (via tvl_fetcher, injectable for tests).

    unique_users_7d semantics CHANGED 2026-10-04 (ADR-003): distinct
    transaction SENDERS that called the project's contracts, not distinct
    token-transfer senders. The score formula itself is unchanged.
    """
    tvl_fetcher = tvl_fetcher or fetch_project_tvl_onchain  # resolved at call time (patchable)
    metrics: dict[str, dict] = {}
    for project in projects:
        project_id = project["id"]
        contracts = [c.lower() for c in (project.get("contracts") or [])]
        wm = window_metrics.get(project_id) or {}

        created_at = _parse_ts(project["created_at"]) if project.get("created_at") else now

        metrics[project_id] = {
            "usdc_gas_7d": wm.get("usdc_gas", Decimal("0")),
            "unique_users_7d": wm.get("unique_users", Decimal("0")),
            "tvl_usd": tvl_fetcher(rpc_pool, contracts),
            "age_bonus": contract_age_bonus(created_at, now),
            # Reported alongside the score, NOT part of the formula:
            "tx_count_7d": wm.get("tx_count", 0),
            "failed_tx_7d": wm.get("failed_tx_count", 0),
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
            "tx_count_7d": int(m.get("tx_count_7d", 0)),
            "failed_tx_7d": int(m.get("failed_tx_7d", 0)),
            "computed_at": computed_at.isoformat(),
        })
    return rows


def build_network_stats(window: dict, computed_at: datetime) -> dict:
    """
    Pure function: network_window_stats() row -> network_stats row for the
    dashboard stat strip. Chain-wide, independent of which contracts are
    tracked as projects. total_volume_7d is ERC-20 transfer volume of the
    1:1-USD tokens only (USDC, USYC); EURC and native gas are never added.
    """
    return {
        "total_volume_7d": str(Decimal(str(window["total_volume_usd"]))),
        "total_tx_7d": int(window["total_tx"]),
        "total_unique_users_7d": int(window["unique_users"]),
        "computed_at": computed_at.isoformat(),
    }


def run():
    client = get_client()
    now = datetime.now(timezone.utc)

    window = fetch_network_window_stats(client, SCORE_WINDOW_DAYS)
    network_stats = build_network_stats(window, now)
    upsert_network_stats(client, network_stats)
    print(f"Updated network_stats: {network_stats} "
          f"(rollup days in window: {window.get('days_with_data')}/{SCORE_WINDOW_DAYS})")

    projects = fetch_projects(client)
    if not projects:
        print("No tracked projects yet. Nothing to score.")
        return

    window_metrics = index_window_metrics(fetch_project_window_metrics(client, SCORE_WINDOW_DAYS))
    rpc_pool = get_web3_pool()

    metrics = build_project_metrics(projects, window_metrics, rpc_pool, now)
    rows = compute_all_scores(metrics, now)

    upsert_project_scores(client, rows)
    print(f"Wrote {len(rows)} project_scores rows for computed_at={now.isoformat()} "
          f"({len(window_metrics)} projects had activity in the window).")


if __name__ == "__main__":
    start = time.monotonic()
    try:
        run()
    except Exception as exc:
        print(f"Scoring run failed: {exc}", file=sys.stderr)
        raise
    print(f"Finished in {time.monotonic() - start:.1f}s")
