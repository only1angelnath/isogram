"""
reclassify_existing_eoas.py — ONE-TIME cleanup script (2026-09-30).

The EOA check in discovery.py's classify_candidates() didn't exist when the
first batch of 21 candidates was processed into needs_review (category
NULL on all of them). Some of those are plain wallet addresses, not
contracts — this script re-checks exactly that batch (status='needs_review'
AND category IS NULL) against eth_getCode and moves any EOA to 'rejected',
so they stop cluttering the manual-review queue. Real contracts with
category still NULL are left untouched — they're genuinely still "checked,
no automated source found anything, needs a human."

Safe to run multiple times — only touches rows matching that exact filter,
and an already-'rejected' row no longer matches it on a second run.

Usage: python reclassify_existing_eoas.py
"""

from datetime import datetime, timezone

from db import get_client
from discovery import _is_eoa
from worker import _StickyPoolIndex, get_web3_pool


def main():
    client = get_client()
    pool = get_web3_pool()
    sticky = _StickyPoolIndex()
    now = datetime.now(timezone.utc).isoformat()

    resp = (
        client.table("discovered_contracts")
        .select("contract_address")
        .eq("status", "needs_review")
        .is_("category", "null")
        .execute()
    )
    rows = resp.data or []
    print(f"Checking {len(rows)} needs_review/category=null candidates for EOAs...")

    rejected = 0
    for row in rows:
        addr = row["contract_address"]
        if _is_eoa(pool, sticky, addr):
            client.table("discovered_contracts").update(
                {"status": "rejected", "updated_at": now}
            ).eq("contract_address", addr).execute()
            rejected += 1
            print(f"  {addr}: EOA -> rejected")
        else:
            print(f"  {addr}: contract, left as needs_review")

    print(f"Done. {rejected} of {len(rows)} were EOAs and moved to 'rejected'.")


if __name__ == "__main__":
    main()
