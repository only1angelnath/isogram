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

# PostgREST (Supabase's REST layer) caps a single response at this many rows
# by default (db-max-rows), silently — a query matching more rows than this
# just returns the first PAGE_SIZE with no error. Confirmed live 2026-09-27:
# total_tx_7d was stuck at exactly 1000 regardless of real 7-day volume,
# because fetch_gas_events_since had no pagination at all. Every fetch
# function below now pages through with .range() until a page comes back
# shorter than PAGE_SIZE (the signal there's nothing left).
PAGE_SIZE = 1000


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


def _fetch_all_pages(build_query):
    """
    Page through a PostgREST query past its default PAGE_SIZE row cap.
    `build_query` is a zero-arg callable that returns a FRESH query builder
    each call (Supabase's query objects are single-use) — e.g.
    `lambda: client.table("gas_events").select("...").gte("ts", since_iso)`.
    Applies .range() on top of whatever filters build_query() already set,
    and stops once a page comes back with fewer than PAGE_SIZE rows.
    """
    rows: list[dict] = []
    start = 0
    while True:
        end = start + PAGE_SIZE - 1
        result = build_query().range(start, end).execute()
        page = result.data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    return rows


def fetch_projects(client: Client) -> list[dict]:
    """All tracked projects: id, contracts, created_at."""
    result = client.table("projects").select("id, contracts, created_at").execute()
    return result.data or []


def fetch_gas_events_since(client: Client, since_iso: str) -> list[dict]:
    """gas_events rows with ts >= since_iso: project_id, usdc_gas_paid. Paginated (see PAGE_SIZE)."""
    return _fetch_all_pages(
        lambda: client.table("gas_events").select("project_id, usdc_gas_paid").gte("ts", since_iso)
    )


def fetch_token_flows_since(client: Client, since_iso: str) -> list[dict]:
    """
    token_flows rows with ts >= since_iso. Used for unique_users_7d (see
    docs/decisions/ADR-002-scoring-formula.md) and, network-wide, for
    total_volume_7d (usd_value) — see compute_scores.py's
    build_network_stats(). Paginated (see PAGE_SIZE).
    """
    return _fetch_all_pages(
        lambda: client.table("token_flows").select(
            "token_address, from_address, to_address, amount, usd_value, ts"
        ).gte("ts", since_iso)
    )


def prune_rows_before(client: Client, table: str, id_column: str, cutoff_iso: str, chunk_size: int = 500) -> int:
    """
    Delete rows from `table` with ts < cutoff_iso, in chunks of chunk_size
    rather than one large statement. Mirrors the reasoning behind
    ingestion/db.py's UPSERT_CHUNK_SIZE: a single DELETE spanning millions
    of rows risks the exact same Postgres statement-timeout (57014) that
    hit the backfill's large upserts. Selects a batch of ids first, deletes
    just those, and repeats until nothing older than cutoff_iso remains.
    Returns the total number of rows deleted.
    """
    total_deleted = 0
    while True:
        batch = (
            client.table(table)
            .select(id_column)
            .lt("ts", cutoff_iso)
            .limit(chunk_size)
            .execute()
        )
        rows = batch.data or []
        if not rows:
            break
        ids = [row[id_column] for row in rows]
        client.table(table).delete().in_(id_column, ids).execute()
        total_deleted += len(ids)
        if len(rows) < chunk_size:
            break
    return total_deleted


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


def upsert_network_stats(client: Client, row: dict) -> None:
    """
    Overwrite the single network_stats row (id=1) with this run's totals —
    a live snapshot, not a history (unlike project_scores). See
    supabase/migrations/20260924080000_network_stats.sql.
    """
    client.table("network_stats").upsert({**row, "id": 1}).execute()
