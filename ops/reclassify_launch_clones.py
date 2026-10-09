"""
One-off: move launchpad CLONE TOKENS out of the 'launchpad' category into 'token'.

Why: until 2026-10-09 discovery filed any token whose proxy implementation name contained
"launch" (e.g. ArgusV4LaunchToken7) under 'launchpad'. By construction every project in that
category was therefore a clone token, not a launchpad platform - hence 350+ "launchpads".
(ingestion/discovery.py no longer produces the category; this fixes the rows already stored.)

Safe by default: prints what WOULD change and exits. Pass --apply to write.
Idempotent: a second run finds nothing to do. Hand-seeded rows are never touched.

Run from the repo root so .env is found:
    PYTHONPATH=ingestion python3 ops/reclassify_launch_clones.py            # preview
    PYTHONPATH=ingestion python3 ops/reclassify_launch_clones.py --apply    # write
"""

import sys

from dotenv import load_dotenv

load_dotenv()

CHUNK = 100


def fetch_launchpad_projects(client) -> list:
    rows, last = [], None
    while True:
        q = client.table("projects").select("id, name, category, seeded").eq("category", "launchpad")
        if last is not None:
            q = q.gt("id", last)
        page = q.order("id").limit(1000).execute().data or []
        rows.extend(page)
        if len(page) < 1000:
            return rows
        last = page[-1]["id"]


def run(client, apply: bool) -> dict:
    rows = fetch_launchpad_projects(client)
    movable = [r for r in rows if not r.get("seeded")]
    skipped = len(rows) - len(movable)
    print(f"projects in category 'launchpad': {len(rows)} ({skipped} hand-seeded, left alone)")
    print(f"to move to 'token': {len(movable)}")
    for r in movable[:8]:
        print(f"  e.g. {r['name'][:44]:44} {r['id'][:20]}")
    if not apply:
        print("\nPREVIEW ONLY - nothing written. Re-run with --apply to make the change.")
        return {"found": len(rows), "moved": 0}
    ids = [r["id"] for r in movable]
    for i in range(0, len(ids), CHUNK):
        client.table("projects").update({"category": "token"}).in_("id", ids[i:i + CHUNK]).execute()
    # keep the discovery ledger consistent so a later re-promotion cannot resurrect the old label
    client.table("discovered_contracts").update({"category": "token"}).eq("category", "launchpad").execute()
    left = len(fetch_launchpad_projects(client)) - skipped
    print(f"\nmoved {len(ids)} projects to 'token'; still unmoved (should be 0): {left}")
    return {"found": len(rows), "moved": len(ids)}


if __name__ == "__main__":
    from db import get_client

    run(get_client(), apply="--apply" in sys.argv)
