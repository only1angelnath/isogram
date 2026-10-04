"""
dry_run_rollup.py - fetch the last N blocks from the LIVE RPC pool, aggregate
them exactly as the real worker does, and print a summary. Writes NOTHING to
the database. Run this once before deploying the rollup worker to confirm:
  * eth_getBlockReceipts works on whichever endpoint the pool picks,
  * receipts carry from / effectiveGasPrice / status (the aggregator fails
    loudly on a missing effectiveGasPrice and warns on a missing from),
  * real throughput (blocks/s) vs the chain's ~1.97 blocks/s.

Usage (from ingestion/, with the same env as the worker, e.g. .env):
    python dry_run_rollup.py [N_BLOCKS]      # default 50
"""

import json
import sys
import time

from dotenv import load_dotenv

load_dotenv()

from rollup import process_batch
from worker import _block_number_on_pool, _StickyPoolIndex, get_web3_pool


def main(n: int) -> None:
    pool = get_web3_pool()
    sticky = _StickyPoolIndex()
    tip = _block_number_on_pool(pool, sticky)
    blocks = list(range(tip - n + 1, tip + 1))
    print(f"Pool size {len(pool)}; chain tip {tip}; fetching {n} blocks ({blocks[0]}..{blocks[-1]})")

    t0 = time.monotonic()
    acc = process_batch(pool, sticky, blocks, set())
    dt = time.monotonic() - t0

    for day, net in sorted(acc.network.items()):
        print(f"  {day}: " + ", ".join(f"{k}={v}" for k, v in net.items()))
    print(f"  distinct senders: {sum(len(s) for s in acc.addresses.values())}, "
          f"receipts missing 'from': {acc.missing_from}")
    print(f"  contract rows: {len(acc.contracts)}, token rows: {len(acc.tokens)}")
    print(f"  payload size: {len(json.dumps(acc.to_payload())) / 1024:.0f} KB")
    print(f"  {n / dt:.1f} blocks/s ({dt:.1f}s); endpoint index that worked last: {sticky.index} "
          f"(0 = first in pool). Chain produces ~1.97 blocks/s.")
    print("NOTHING WAS WRITTEN.")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 50)
