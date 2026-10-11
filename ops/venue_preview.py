"""
Read-only: scan each Arc venue's own pools exactly like the hourly job, apply the anomaly filter at several
trader thresholds, and print the result next to CoinGecko's Arc exchanges page (snapshot pasted into the
project notes on 2026-10-09). Writes NOTHING.

Columns: raw = every pool; t5 / t10 / t20 = volume kept when pools need at least 5 / 10 / 20 traders (and
turnover <= 25x); excl = volume excluded at the default threshold (10). A `*` after the venue means its pool
list was longer than the scan cap, so its volume is a lower bound. The snapshot is a day old: look for the
same SHAPE (same venues on top, similar proportions), not an exact match. Flagged when t10 is < 0.4x or
> 2.5x of CoinGecko.

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
    pools, scanned, calls, incomplete = [], {}, 0, []
    for dex in sorted(names):
        vp, outcome = v.scan_venue(dex, api_key, fetch=fetch_page or v.fetch_venue_page)
        calls += outcome["calls"]
        if outcome["status"] != "complete":
            incomplete.append((dex, outcome["status"]))
            continue
        pools += vp
        scanned[dex] = {"truncated": outcome["truncated"]}
    variants = {t: {r["dex_id"]: r for r in v.aggregate(pools, names, scanned, min_traders=t)} for t in (5, 10, 20)}
    raw = {d: sum(p["volume"] for p in pools if p["dex_id"] == d) for d in scanned}
    print(f"scanned {len(pools)} pools in {calls} calls across {len(scanned)} venues "
          f"(thresholds: >= N traders and turnover <= {v.MAX_TURNOVER:.0f}x; production default N={v.MIN_TRADERS})")
    print(f"{'venue':24} {'kind':9} {'raw':>12} {'t5':>11} {'t10':>11} {'t20':>11} {'excl':>12} {'CoinGecko':>11} {'t10/CG':>7}")
    totals = [0.0, 0.0, 0.0, 0.0]
    for dex in sorted(scanned, key=lambda d: -variants[10][d]["volume_24h_usd"]):
        k5, k10, k20 = (variants[t][dex]["volume_24h_usd"] for t in (5, 10, 20))
        if raw[dex] <= 0 and dex not in SNAPSHOT:
            continue
        snap = SNAPSHOT.get(dex)
        ratio = "-" if snap is None else f"{k10 / snap:>6.0%}"
        flag = "  <-- CHECK" if snap and not 0.4 <= k10 / snap <= 2.5 else ""
        star = "*" if scanned[dex]["truncated"] else " "
        print(f"{(names.get(dex) or dex)[:23]:23}{star} {variants[10][dex]['kind']:9} {raw[dex]:>12,.0f} {k5:>11,.0f} {k10:>11,.0f} {k20:>11,.0f} "
              f"{variants[10][dex]['excluded_volume_usd']:>12,.0f} {(snap or 0):>11,.0f} {ratio:>7}{flag}")
        totals = [totals[0] + raw[dex], totals[1] + k5, totals[2] + k10, totals[3] + k20]
    print(f"{'TOTAL':24} {'':9} {totals[0]:>12,.0f} {totals[1]:>11,.0f} {totals[2]:>11,.0f} {totals[3]:>11,.0f} "
          f"{'':>12} {sum(SNAPSHOT.values()):>11,.0f}")
    for dex, status in incomplete:
        print(f"INCOMPLETE: {dex} ({status})")
    missing = [d for d in SNAPSHOT if d not in names]
    if missing:
        print("CoinGecko lists these venue ids but GeckoTerminal's list does not:", missing)
    return variants, raw, scanned


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    key = os.environ.get("COINGECKO_PRO_API_KEY")
    if not key:
        sys.exit("COINGECKO_PRO_API_KEY not found (set it in .env)")
    run(key)
