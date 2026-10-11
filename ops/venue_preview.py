"""
Read-only: scan GeckoTerminal's top Arc pools and print per-venue 24h volume, next to the figures from
CoinGecko's Arc exchanges page that were pasted into the project notes on 2026-10-09. Writes NOTHING.

The CoinGecko snapshot was taken at a different moment, so expect drift of tens of percent in a day with
real trading. What matters is the SHAPE: the same venues on top in roughly the same proportions, and
no venue wildly lower (that would mean the scan misses part of its pools).

Run from the repo root:
    PYTHONPATH=ingestion python3 ops/venue_preview.py
"""

import os
import sys

SNAPSHOT = {  # GeckoTerminal venue id -> 24h volume (USD) on CoinGecko's exchanges page
    "aero-arc": 1_157_887,
    "uniswap-v3-arc": 1_118_619,
    "faze": 455_430,
    "uniswap-v4-arc": 415_074,
    "argus": 228_213,
    "archery-v3": 120_929,
    "o1-launchpad-arc": 73_636.51,
    "synthra-arc": 19_028.00,
    "foci": 4_524.93,
}


def run(api_key, fetch_names=None, fetch_page=None):
    import venues as v

    names = (fetch_names or v.fetch_dex_names)(api_key)[1]
    pools, scan = v.collect_pools(api_key, fetch=fetch_page or v.fetch_pools_page)
    rows = v.aggregate(pools, names)
    print(f"scanned {len(pools)} pools in {scan['pages']} pages; stopped: {scan['stopped']}; "
          f"complete: {scan['complete']}; sorted by volume: {scan['sorted']}")
    total = sum(r["volume_24h_usd"] for r in rows)
    print(f"total sampled 24h volume: ${total:,.0f}   (CoinGecko snapshot total: ${sum(SNAPSHOT.values()):,.0f})\n")
    print(f"{'venue':26} {'kind':9} {'24h volume':>13} {'share':>6} {'pools':>5}  {'vs CoinGecko':>13}  most traded pool")
    for r in sorted(rows, key=lambda r: -r["volume_24h_usd"]):
        if r["volume_24h_usd"] <= 0 and r["dex_id"] not in SNAPSHOT:
            continue
        snap = SNAPSHOT.get(r["dex_id"])
        cmp = "-" if snap is None else f"{r['volume_24h_usd'] / snap:>5.0%} of theirs"
        flag = "  <-- CHECK" if snap and not 0.4 <= r["volume_24h_usd"] / snap <= 2.5 else ""
        print(f"{r['name'][:26]:26} {r['kind']:9} {r['volume_24h_usd']:>13,.0f} {r['volume_24h_usd'] / total if total else 0:>6.1%} "
              f"{r['active_pools']:>5}  {cmp:>13}  {r['top_pool_name'] or '-'}{flag}")
    missing = [d for d in SNAPSHOT if d not in {r['dex_id'] for r in rows}]
    if missing:
        print("\nCoinGecko lists these venue ids but GeckoTerminal's list does not:", missing)
    return rows, scan


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    key = os.environ.get("COINGECKO_PRO_API_KEY")
    if not key:
        sys.exit("COINGECKO_PRO_API_KEY not found (set it in .env)")
    run(key)
