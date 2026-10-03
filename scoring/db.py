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
# because fetch_gas_events_since had no pagination at all.
#
# CHANGED 2026-10-03: the original fix paginated with .range(start, end) —
# OFFSET-based. OFFSET pagination gets slower every page: fetching page 290
# means Postgres scans and discards the first 289,000 rows first, every
# single call. With gas_events now holding hundreds of thousands of rows in
# the 7-day window, this hit Postgres's statement timeout (57014) for real,
# killing the entire scoring run outright (not just one slow page — the
# whole job crashed on fetch_gas_events_since before computing anything).
#
# Fixed with keyset pagination instead: page by "cursor_column > last_seen
# value" (an indexed, unique column — tx_hash for gas_events' primary key,
# id for token_flows' bigserial primary key) rather than OFFSET. Every page
# is an equally-fast indexed range scan regardless of total table size —
# no scaling cliff as the table grows.
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


def _fetch_all_pages_keyset(build_query, cursor_column: str):
    """
    Page through a PostgREST query past its default PAGE_SIZE row cap using
    keyset pagination (WHERE cursor_column > last_seen, ORDER BY
    cursor_column, LIMIT PAGE_SIZE) instead of OFFSET — see PAGE_SIZE's
    comment for why OFFSET doesn't scale here. `build_query` is a zero-arg
    callable that returns a FRESH query builder each call (Supabase's query
    objects are single-use) with whatever filters already applied, but
    WITHOUT its own .order()/.limit() — those are added here.
    `cursor_column` must be unique and indexed (a primary key) for this to
    stay fast and to guarantee every row is seen exactly once.
    """
    rows: list[dict] = []
    last_value = None
    while True:
        query = build_query()
        if last_value is not None:
            query = query.gt(cursor_column, last_value)
        result = query.order(cursor_column).limit(PAGE_SIZE).execute()
        page = result.data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        last_value = page[-1][cursor_column]
    return rows


def fetch_projects(client: Client) -> list[dict]:
    """All tracked projects: id, contracts, created_at."""
    result = client.table("projects").select("id, contracts, created_at").execute()
    return result.data or []


def fetch_gas_events_since(client: Client, since_iso: str) -> list[dict]:
    """
    gas_events rows with ts >= since_iso: tx_hash, project_id, usdc_gas_paid.
    Keyset-paginated on tx_hash (the primary key) — see PAGE_SIZE's comment.
    tx_hash is included in the select solely to serve as the pagination
    cursor; callers that only need project_id/usdc_gas_paid can ignore it.
    """
    return _fetch_all_pages_keyset(
        lambda: client.table("gas_events").select("tx_hash, project_id, usdc_gas_paid").gte("ts", since_iso),
        cursor_column="tx_hash",
    )


def fetch_token_flows_since(client: Client, since_iso: str) -> list[dict]:
    """
    token_flows rows with ts >= since_iso. Used for unique_users_7d (see
    docs/decisions/ADR-002-scoring-formula.md) and, network-wide, for
    total_volume_7d (usd_value) — see compute_scores.py's
    build_network_stats(). Keyset-paginated on id (the bigserial primary
    key) — see PAGE_SIZE's comment. id is included in the select solely to
    serve as the pagination cursor.
    """
    return _fetch_all_pages_keyset(
        lambda: client.table("token_flows").select(
            "id, token_address, from_address, to_address, amount, usd_value, ts"
        ).gte("ts", since_iso),
        cursor_column="id",
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
