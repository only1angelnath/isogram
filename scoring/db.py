"""
db.py — Supabase/Postgres client helpers for the scoring job.

Handles: reading projects/gas_events/token_flows, writing project_scores.
Mirrors ingestion/db.py's pattern but is a separate module on purpose (see
docs/SCAFFOLD.md — scoring/ is its own deployable unit with its own
requirements.txt, independent of ingestion/).

Schema reference: docs/SCHEMA.md
"""

import os

from supabase import Client, create_client


def get_client() -> Client:
    """
    Build a Supabase client from environment variables. Same env vars as
    ingestion/db.py (SUPABASE_URL, SUPABASE_SERVICE_KEY) — the service key is
    required since this job writes to project_scores.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set (see .env.example). "
            "The service key is required, not the anon key, since this job writes data."
        )
    return create_client(url, key)


def fetch_projects(client: Client) -> list[dict]:
    """All tracked projects: id, contracts, created_at."""
    result = client.table("projects").select("id, contracts, created_at").execute()
    return result.data or []


def fetch_gas_events_since(client: Client, since_iso: str) -> list[dict]:
    """gas_events rows with ts >= since_iso: project_id, usdc_gas_paid."""
    result = (
        client.table("gas_events")
        .select("project_id, usdc_gas_paid")
        .gte("ts", since_iso)
        .execute()
    )
    return result.data or []


def fetch_token_flows_since(client: Client, since_iso: str) -> list[dict]:
    """
    token_flows rows with ts >= since_iso. Used for unique_users_7d — see
    docs/decisions/ADR-002-scoring-formula.md for why this comes from
    token_flows rather than gas_events (which has no sender column).
    """
    result = (
        client.table("token_flows")
        .select("token_address, from_address, to_address, amount, ts")
        .gte("ts", since_iso)
        .execute()
    )
    return result.data or []


def fetch_all_token_flows(client: Client) -> list[dict]:
    """
    Every token_flows row, all-time. Used for TVL (scoring/tvl.py), which
    needs a contract's full net balance, not just the trailing 7-day window.
    """
    result = (
        client.table("token_flows")
        .select("token_address, from_address, to_address, amount")
        .execute()
    )
    return result.data or []


def upsert_project_scores(client: Client, rows: list[dict]) -> None:
    """
    Insert one project_scores row per project for this computation run. Not
    an upsert in the dedup sense — (project_id, computed_at) is the primary
    key and computed_at is fresh each run, so every call adds new rows,
    building the historical record the badge/score trends read from (see
    docs/SCHEMA.md retention policy).
    """
    if not rows:
        return
    client.table("project_scores").insert(rows).execute()
