"""
backfill_historical.py — closes the FIXED historical gap recorded by
jump_and_seed_backfill.py in historical_backfill_state.

Unlike worker.py's run() (which always targets the current chain tip, a
moving target that made the original backfill attempts unable to ever
finish — see docs/BUGS.md #5's history), this processes a bounded,
non-moving range [range_start..range_end] set once at jump time. Progress
is measurable and the job can actually reach completion.

Reuses the exact same RPC pool, retry/backoff, sticky-endpoint selection,
and decode logic as worker.py (process_blocks_concurrent) — this is not a
parallel reimplementation, just a different source of "which blocks to
process next" and a different table to checkpoint against. Writes go to
the same gas_events/token_flows tables as live ingestion; tx_hash's
primary key means there's no risk of duplicate rows if a range is ever
reprocessed.

Safe to run alongside the regular ingestion-cron workflow — they track
completely separate checkpoint state (sync_state vs
historical_backfill_state), so there's no race to worry about.

Usage: python backfill_historical.py   (call repeatedly until it reports
"Nothing to do" — see backfill.yml's loop)
"""

import sys

from db import get_client, load_contract_project_map, upsert_gas_events, upsert_token_flows
from worker import MAX_BLOCKS_PER_RUN, _StickyPoolIndex, get_web3_pool, process_blocks_concurrent


def run():
    client = get_client()

    state = client.table("historical_backfill_state").select("*").eq("id", 1).execute()
    if not state.data:
        print(
            "No historical_backfill_state row found — nothing to backfill. "
            "Nothing to do. (Run jump_and_seed_backfill.py first if a backfill "
            "was intended, or this one's already been cleaned up after completion.)"
        )
        return

    row = state.data[0]
    next_block = row["next_block"]
    range_end = row["range_end"]

    if next_block > range_end:
        print(f"Historical backfill already complete (reached {range_end}). Nothing to do.")
        return

    pool = get_web3_pool()
    sticky = _StickyPoolIndex()
    end_block = min(range_end, next_block + MAX_BLOCKS_PER_RUN - 1)
    contract_project_map = load_contract_project_map(client)

    print(f"Historical backfill: blocks {next_block}..{end_block} (target range end: {range_end})")

    try:
        block_numbers = list(range(next_block, end_block + 1))
        all_gas_events, all_token_flows = process_blocks_concurrent(pool, block_numbers, contract_project_map, sticky)
    except Exception as exc:
        # Deliberately do NOT advance next_block on failure — same
        # checkpoint-safety contract as worker.py's run().
        print(f"Historical backfill failed partway through: {exc}", file=sys.stderr)
        raise

    upsert_gas_events(client, all_gas_events)
    upsert_token_flows(client, all_token_flows)
    client.table("historical_backfill_state").update({"next_block": end_block + 1}).eq("id", 1).execute()

    remaining = range_end - end_block
    print(
        f"Done. Wrote {len(all_gas_events)} gas events, {len(all_token_flows)} token flows. "
        f"Historical progress now at {end_block} / {range_end} ({remaining} blocks remaining)."
    )


if __name__ == "__main__":
    run()
