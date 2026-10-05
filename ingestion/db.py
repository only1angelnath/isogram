"""
db.py — Supabase/Postgres client helpers for the ingestion worker.

Handles: checkpoint read/write (sync_state), upserts into gas_events and
token_flows, and resolving a contract address to a known project_id.

Schema reference: docs/SCHEMA.md
"""

import os
from typing import Optional

from supabase import Client, create_client


def get_client() -> Client:
    """
    Build a Supabase client from environment variables. Raises a clear error
    immediately if the required env vars are missing, rather than failing
    confusingly later on the first query.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set (see .env.example). "
            "The service key is required, not the anon key, since the worker writes data."
        )
    return create_client(url, key)


# --- Checkpointing (sync_state) -------------------------------------------

def get_last_synced_block(client: Client, default_start_block: int) -> int:
    """
    Read the ingestion checkpoint. If no row exists yet (first run ever),
    return `default_start_block` instead of guessing — the caller decides
    where a cold start should begin (see docs/IMPLEMENTATION_PLAN.md).
    """
    result = client.table("sync_state").select("last_block_number").eq("id", 1).execute()
    if not result.data:
        return default_start_block
    return int(result.data[0]["last_block_number"])


def update_last_synced_block(client: Client, block_number: int) -> None:
    """
    Advance the checkpoint. Only call this after a batch has been fully and
    successfully written — advancing early risks skipping blocks on a
    mid-batch failure (see docs/AUDIT.md).
    """
    client.table("sync_state").upsert(
        {"id": 1, "last_block_number": block_number}
    ).execute()


# --- Project resolution -----------------------------------------------------

def build_contract_project_map(project_rows: list[dict]) -> dict[str, str]:
    """
    Pure function: turn a list of `projects` rows (each with an `id` and a
    `contracts` list of addresses) into a flat {lowercased_address: project_id}
    lookup. Kept separate from the network call so it's unit-testable without
    a live database.
    """
    lookup: dict[str, str] = {}
    for row in project_rows:
        project_id = row["id"]
        for address in row.get("contracts", []) or []:
            lookup[address.lower()] = project_id
    return lookup


PROJECTS_PAGE_SIZE = 1000  # PostgREST's default response cap


def load_contract_project_map(client: Client) -> dict[str, str]:
    """
    Fetch all known projects and build the contract -> project_id lookup.
    Call this once per worker run (or periodically) rather than per-block —
    the projects table changes rarely compared to block volume.
    """
    # Keyset-paginated on id (primary key). Discovery promotes dozens of
    # projects per run; an unpaginated select silently stops at PostgREST's
    # 1000-row cap, after which contracts of later projects would be quietly
    # unmapped (the same silent-truncation class as docs/BUGS.md's gas_events bug).
    rows: list[dict] = []
    last_id = None
    while True:
        query = client.table("projects").select("id, contracts")
        if last_id is not None:
            query = query.gt("id", last_id)
        page = query.order("id").limit(PROJECTS_PAGE_SIZE).execute().data or []
        rows.extend(page)
        if len(page) < PROJECTS_PAGE_SIZE:
            break
        last_id = page[-1]["id"]
    return build_contract_project_map(rows)


def resolve_project_id(contract_address: str, contract_project_map: dict[str, str]) -> Optional[str]:
    """
    Look up a project_id for a contract address, or None if it's not a
    tracked project yet. None is a valid, expected value here — gas_events
    and token_flows both allow a null project_id (see docs/SCHEMA.md).
    """
    return contract_project_map.get(contract_address.lower())


# --- Upserts -----------------------------------------------------------------
#
# UPSERT_CHUNK_SIZE (2026-09-27): a real backfill run with MAX_BLOCKS_PER_RUN
# =20000 produced ~210,000 gas_events rows and sent them as ONE upsert() call
# — Postgres killed it every single time with:
#   postgrest.exceptions.APIError: {'message': 'canceling statement due to
#   statement timeout', 'code': '57014', ...}
# Because the checkpoint only advances on full success, this meant 5+
# consecutive backfill iterations (~5h50m of wall-clock time, all the RPC
# fetching work included) each redid the exact same block range from
# scratch and threw it away at the very last step. Chunking the upsert into
# smaller batches means a large run finishes via many small, fast
# statements instead of one huge one that can't complete in time — this is
# what makes a large MAX_BLOCKS_PER_RUN actually safe to use, independent
# of how big it gets.
UPSERT_CHUNK_SIZE = int(os.environ.get("UPSERT_CHUNK_SIZE", "500"))


def _chunks(rows: list[dict], size: int):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def upsert_gas_events(client: Client, events: list[dict]) -> None:
    """
    Batch upsert into gas_events, in chunks of UPSERT_CHUNK_SIZE rows so a
    large batch can't blow Postgres's statement timeout (see comment above).
    Each dict must have: tx_hash, contract_address, project_id (nullable),
    usdc_gas_paid, block_number, ts. tx_hash is the primary key, so a rerun
    over an already-processed block range updates rather than duplicates
    rows — true per-chunk as well as for the batch as a whole.
    """
    if not events:
        return
    for chunk in _chunks(events, UPSERT_CHUNK_SIZE):
        client.table("gas_events").upsert(chunk, on_conflict="tx_hash").execute()


def upsert_token_flows(client: Client, flows: list[dict]) -> None:
    """
    Batch insert into token_flows, in chunks of UPSERT_CHUNK_SIZE rows (see
    upsert_gas_events / the module comment above for why). This table has no
    natural unique key (bigserial id), so callers are responsible for not
    re-submitting the same event twice — the worker's block-range
    checkpointing handles that; chunking here doesn't change that contract,
    it just splits one large insert into several smaller ones.
    """
    if not flows:
        return
    for chunk in _chunks(flows, UPSERT_CHUNK_SIZE):
        client.table("token_flows").insert(chunk).execute()