"""
db.py — Supabase/Postgres read helpers for the FastAPI app.

This is a read-only layer: the API never writes to projects, gas_events,
token_flows, or project_scores (those are ingestion/ and scoring/'s job).
See docs/AUDIT.md — no unauthenticated write endpoints, full stop.
"""

import os
from datetime import datetime, timedelta, timezone

from supabase import Client, create_client

# PostgREST silently caps any response at 1000 rows (no error) - the cause of
# several past bugs in this codebase (docs/BUGS.md). Anything that can grow
# past that is read through keyset pagination (WHERE col > last ORDER BY col).
PAGE_SIZE = 1000

# Tokens the rollups track (6-decimal ERC-20 views; docs/architecture_essentials.md).
TRACKED_TOKENS = {
    "USDC": "0x3600000000000000000000000000000000000000",
    "EURC": "0xbef5f6d51cb62b58e6a8f77868681825c6fe21c1",
    "USYC": "0x8a5d989bbb96929f689b0200f435f53da42bf490",
}



def get_client() -> Client:
    """
    Build a Supabase client. Prefers the anon/read key over the service key
    if both are set, since the API only ever reads (see module docstring) —
    but falls back to the service key so a single-key deployment still
    works. Either way this client is never used for writes here.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and (SUPABASE_ANON_KEY or SUPABASE_SERVICE_KEY) must be set "
            "(see .env.example)."
        )
    return create_client(url, key)


def _fetch_all_pages_keyset(build_query, cursor_column: str) -> list[dict]:
    """Page past PostgREST's 1000-row cap. `build_query` returns a FRESH builder
    each call (they are single-use). `cursor_column` must be unique + indexed."""
    rows: list[dict] = []
    last_value = None
    while True:
        query = build_query()
        if last_value is not None:
            query = query.gt(cursor_column, last_value)
        page = query.order(cursor_column).limit(PAGE_SIZE).execute().data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        last_value = page[-1][cursor_column]


def _utc_today():
    return datetime.now(timezone.utc).date()


def fetch_projects(client: Client) -> list[dict]:
    """Every tracked project. Keyset-paginated: discovery adds dozens per run."""
    return _fetch_all_pages_keyset(
        lambda: client.table("projects").select("id, name, category, contracts, created_at, seeded"),
        cursor_column="id",
    )


def fetch_project(client: Client, project_id: str) -> dict | None:
    result = (
        client.table("projects")
        .select("id, name, category, contracts, created_at, seeded")
        .eq("id", project_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def fetch_all_latest_scores(client: Client) -> list[dict]:
    """
    The LATEST project_scores row per project, via the latest_project_scores
    view (migration 20261005020000). The previous version read every historical
    row unpaginated: one row per project per scoring run passes PostgREST's
    1000-row cap within a day at ~160 projects, after which the API would have
    served arbitrary stale scores silently.
    """
    return _fetch_all_pages_keyset(
        lambda: client.table("latest_project_scores").select("project_id, score, tvl_usd, usdc_gas_7d, unique_users_7d, tx_count_7d, failed_tx_7d, computed_at"),
        cursor_column="project_id",
    )


def fetch_latest_scores_for_project(client: Client, project_id: str) -> list[dict]:
    result = (
        client.table("latest_project_scores")
        .select("project_id, score, tvl_usd, usdc_gas_7d, unique_users_7d, tx_count_7d, failed_tx_7d, computed_at")
        .eq("project_id", project_id)
        .execute()
    )
    return result.data or []


def fetch_score_history(client: Client, project_id: str, limit: int) -> list[dict]:
    """A project's score history (one row per scoring run), newest first."""
    result = (
        client.table("project_scores")
        .select("project_id, score, tvl_usd, usdc_gas_7d, unique_users_7d, tx_count_7d, failed_tx_7d, computed_at")
        .eq("project_id", project_id)
        .order("computed_at", desc=True)
        .limit(min(limit, PAGE_SIZE))
        .execute()
    )
    return result.data or []


# --- Rollup-backed metrics (2026-10-04, docs/decisions/ADR-003) ------------------

def fetch_network_daily(client: Client, days: int) -> list[dict]:
    """daily_network_metrics rows for the last `days` UTC days, oldest first."""
    since = (_utc_today() - timedelta(days=days - 1)).isoformat()
    result = (
        client.table("daily_network_metrics")
        .select("day, tx_count, failed_tx_count, usdc_gas_paid, contract_creations, blocks, "
                "token_transfer_count, active_addresses, source")
        .gte("day", since)
        .order("day")
        .limit(PAGE_SIZE)
        .execute()
    )
    return result.data or []


def fetch_token_daily(client: Client, days: int, token_address: str | None) -> list[dict]:
    """daily_token_metrics rows for the last `days` UTC days (optionally one token), oldest first."""
    since = (_utc_today() - timedelta(days=days - 1)).isoformat()
    query = (
        client.table("daily_token_metrics")
        .select("day, token_address, transfer_count, volume")
        .gte("day", since)
    )
    if token_address:
        query = query.eq("token_address", token_address.lower())
    return query.order("day").limit(PAGE_SIZE).execute().data or []


def fetch_top_contracts(client: Client, days: int, limit: int) -> list[dict]:
    result = client.rpc("top_contracts", {"p_days": days, "p_limit": limit}).execute()
    return result.data or []


def fetch_project_daily(client: Client, project_id: str, days: int) -> list[dict]:
    result = client.rpc("project_daily_metrics", {"p_project_id": project_id, "p_days": days}).execute()
    return result.data or []


def fetch_network_stats(client: Client) -> dict | None:
    """
    The single network_stats row (see
    supabase/migrations/20260924080000_network_stats.sql). None if the
    scoring job hasn't run yet — never fabricate zeros for a run that
    hasn't happened (same docs/BUGS.md #3 discipline as everything else).
    """
    result = (
        client.table("network_stats")
        .select("total_volume_7d, total_tx_7d, total_unique_users_7d, computed_at")
        .eq("id", 1)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_write_client() -> Client:
    """
    Build a Supabase client using the service key, for the one route
    (POST /submit) that needs to write. Never used for reads — reads stay
    on get_client()'s anon-preferring client, per this module's docstring.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set for the write "
            "client (see .env.example). The anon key cannot write here — "
            "project_submissions has no anon RLS policy at all."
        )
    return create_client(url, key)


def insert_submission(client: Client, submission: dict) -> dict:
    """
    Insert one row into project_submissions. `submission` must already be
    validated (see models.SubmissionRequest) — this function does no
    validation of its own, it just writes what it's given.
    """
    result = client.table("project_submissions").insert(submission).execute()
    return result.data[0] if result.data else {}


def fetch_pipeline_status(client: Client) -> dict | None:
    """How far ingestion has processed: last_block_number, data_through (timestamp of
    the last applied block), checkpoint_updated_at. None if unavailable."""
    rows = client.rpc("pipeline_status", {}).execute().data or []
    return rows[0] if rows else None
