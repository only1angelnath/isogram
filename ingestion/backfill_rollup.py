"""
backfill_rollup.py - fill the historical gap (2026-09-29 .. 2026-10-03) with the SAME
rollup pipeline as live ingestion, against its own checkpoint (historical_backfill_state).

Why a separate job: the live checkpoint was jumped past this range on 2026-10-04. This job
processes the fixed range [range_start, range_end] in atomic sub-batches through
apply_backfill_batch() (exactly-once, see migration 20261007000000), independent of the
live job, so both can run at the same time.

Run `ops/start_gap_backfill.sql` once first. Each invocation processes blocks until its
time budget ends and reports done=true (also written to $GITHUB_OUTPUT) when the range is
complete, which is what stops the workflow from chaining another run.

Sender addresses are only recorded for days still inside the address-retention window
(last 7 days); older backfilled days get tx/gas/failure/deployment/token totals but
active_addresses stays null ("unknown") - never a made-up number.
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

from db import get_client, load_contract_project_map
from rollup import apply_backfill, run_rollup
from worker import _StickyPoolIndex, get_web3_pool


def read_state(client) -> dict:
    rows = client.table("historical_backfill_state").select("range_start, range_end, next_block").eq("id", 1).execute().data
    if not rows:
        raise RuntimeError("historical_backfill_state is empty - run ops/start_gap_backfill.sql first")
    return rows[0]


def run() -> bool:
    client = get_client()
    state = read_state(client)
    next_block, range_end = int(state["next_block"]), int(state["range_end"])
    if next_block > range_end:
        print(f"Backfill already complete (next_block {next_block} > range_end {range_end}).")
        return True

    print(f"Backfilling blocks {next_block}..{range_end} ({range_end - next_block + 1} to go).")
    tracked_map = load_contract_project_map(client)
    pool = get_web3_pool()
    sticky = _StickyPoolIndex()
    window_start = (datetime.now(timezone.utc).date() - timedelta(days=6)).isoformat()

    summary = run_rollup(
        client, pool, sticky, tracked_map,
        last_synced=next_block - 1, latest_block=range_end, max_blocks=range_end - next_block + 1,
        tip_fn=None, apply_fn=apply_backfill, address_min_day=window_start,
    )
    done = summary["checkpoint"] >= range_end
    print(f"Done this run: {summary['blocks']} blocks in {summary['seconds']:.0f}s. "
          f"Checkpoint {summary['checkpoint']}, {max(0, range_end - summary['checkpoint'])} blocks left. "
          f"{'BACKFILL COMPLETE.' if done else 'More runs needed.'}")
    return done


if __name__ == "__main__":
    t0 = time.monotonic()
    finished = run()
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as fh:
            fh.write(f"done={'true' if finished else 'false'}\n")
    print(f"Finished in {time.monotonic() - t0:.1f}s")
