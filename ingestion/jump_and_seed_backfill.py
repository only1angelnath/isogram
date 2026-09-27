"""
jump_and_seed_backfill.py — ONE-TIME operational script (2026-09-27).

Problem: the live ingestion checkpoint (sync_state) was crawling forward
from old blocks toward the current chain tip, but never catching up — the
gap kept growing because it was racing a moving target (new blocks keep
arriving at ~2/sec). Meanwhile the MOST RECENT blocks are exactly what the
scoring formula's rolling 7-day windows (docs/SCHEMA.md) need, and they're
exactly what was missing while the checkpoint sat ~700k+ blocks behind tip.

Fix: jump the live checkpoint forward to near the current chain tip (a
small buffer behind it, not the tip itself, so the very next ingestion run
has real committed blocks to read rather than the bleeding edge). The
skipped middle range becomes a FIXED, bounded backfill job recorded in
historical_backfill_state — see backfill_historical.py — which can
actually finish, unlike chasing the live tip forever.

Run this ONCE, locally (with your .env populated — same vars as the GitHub
secrets: SUPABASE_URL, SUPABASE_SERVICE_KEY, and whichever RPC endpoint
vars you have set). Refuses to run again if historical_backfill_state
already has a row, so it's safe even if you accidentally run it twice.

Usage:
    python jump_and_seed_backfill.py [--buffer-blocks 2000]
"""

import argparse
import sys

from db import get_client, get_last_synced_block
from worker import DEFAULT_START_BLOCK, _StickyPoolIndex, _block_number_on_pool, get_web3_pool


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--buffer-blocks", type=int, default=2000,
        help="How far behind the live chain tip to set the new live checkpoint "
             "(default 2000, ~15-20 minutes at Arc's ~2 blocks/sec)."
    )
    args = parser.parse_args()

    client = get_client()
    pool = get_web3_pool()
    sticky = _StickyPoolIndex()

    old_checkpoint = get_last_synced_block(client, DEFAULT_START_BLOCK)
    chain_tip = _block_number_on_pool(pool, sticky)
    new_checkpoint = chain_tip - args.buffer_blocks

    if new_checkpoint <= old_checkpoint:
        print(
            f"Chain tip ({chain_tip}) minus buffer ({args.buffer_blocks}) is not "
            f"ahead of the current checkpoint ({old_checkpoint}) — nothing to jump.",
            file=sys.stderr,
        )
        sys.exit(1)

    existing = client.table("historical_backfill_state").select("*").eq("id", 1).execute()
    if existing.data:
        print(
            "historical_backfill_state already has a row — refusing to overwrite an "
            "in-progress or completed backfill range. Delete it manually first if you "
            "really want to re-seed (you'll lose track of prior backfill progress).",
            file=sys.stderr,
        )
        sys.exit(1)

    gap_size = new_checkpoint - old_checkpoint
    print(f"Old live checkpoint:      {old_checkpoint}")
    print(f"Current chain tip:        {chain_tip}")
    print(f"New live checkpoint:      {new_checkpoint}  (chain tip - {args.buffer_blocks})")
    print(f"Historical gap to backfill separately: {old_checkpoint + 1}..{new_checkpoint} ({gap_size} blocks)")

    # Order matters: seed the historical range FIRST, using the checkpoint's
    # value at the moment we read it. If this script dies right after this
    # write but before the sync_state update below, the historical row
    # already correctly reflects the range that needs backfilling, and
    # rerunning this script will safely refuse (existing row) rather than
    # double-seed or silently lose the gap.
    client.table("historical_backfill_state").insert({
        "id": 1,
        "range_start": old_checkpoint + 1,
        "range_end": new_checkpoint,
        "next_block": old_checkpoint + 1,
    }).execute()

    client.table("sync_state").upsert({"id": 1, "last_block_number": new_checkpoint}).execute()

    print(
        "\nDone. Live ingestion (ingestion-cron) will resume from the new checkpoint "
        "next time it runs — safe to re-enable its schedule now. Run backfill_historical.py "
        "(via the backfill workflow) to close the recorded gap independently, at whatever pace."
    )


if __name__ == "__main__":
    main()
