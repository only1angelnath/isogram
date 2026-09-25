"""
db.py — Supabase/Postgres read helpers for the FastAPI app.

This is a read-only layer: the API never writes to projects, gas_events,
token_flows, or project_scores (those are ingestion/ and scoring/'s job).
See docs/AUDIT.md — no unauthenticated write endpoints, full stop.
"""

import os

from supabase import Client, create_client



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


def fetch_projects(client: Client) -> list[dict]:
    result = client.table("projects").select("id, name, category, contracts, created_at").execute()
    return result.data or []


def fetch_project(client: Client, project_id: str) -> dict | None:
    result = (
        client.table("projects")
        .select("id, name, category, contracts, created_at")
        .eq("id", project_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def fetch_all_latest_scores(client: Client) -> list[dict]:
    """
    Every project_scores row. Deduping to "latest per project" happens in
    aggregate.latest_score_by_project() — kept out of the query itself since
    Supabase's query builder has no clean DISTINCT ON, and this table stays
    small enough (one row per project per run) for in-process dedup to be
    the simpler, more obviously-correct choice for a hackathon MVP.
    """
    result = (
        client.table("project_scores")
        .select("project_id, score, tvl_usd, usdc_gas_7d, unique_users_7d, computed_at")
        .execute()
    )
    return result.data or []


def fetch_latest_scores_for_project(client: Client, project_id: str) -> list[dict]:
    result = (
        client.table("project_scores")
        .select("project_id, score, tvl_usd, usdc_gas_7d, unique_users_7d, computed_at")
        .eq("project_id", project_id)
        .execute()
    )
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

