"""
venues.py - per-venue (DEX / launchpad) 24h volume on Arc, from GeckoTerminal.

GeckoTerminal tags every pool with the venue ("dex") that hosts it, and Arc has ~22 of them,
including launch platforms (argus, faze, foci, ...). We page through the network-wide pools sorted
by 24h volume (up to 10 pages x 20 pools, ~11 calls) and sum volume per venue. Uniswap V2, V3 and V4
stay separate venues, exactly as GeckoTerminal and CoinGecko list them.

Only a COMPLETE scan is written (it ended because the pages ran out, the volume tail hit zero, or
the 10-page cap was reached). A scan cut short by an error, a 429 or the time budget would
understate every venue, so it is discarded and the previous numbers stay.

Runs after the other refreshes in worker.main(), wrapped like them: it can never fail the job.
"""

import os
import time
from datetime import datetime, timezone

import requests

NETWORK = "arc"
GECKO = "https://pro-api.coingecko.com/api/v3/onchain"
POOLS_URL = GECKO + "/networks/{network}/pools"
DEXES_URL = GECKO + "/networks/{network}/dexes"
SORT = "h24_volume_usd_desc"
MAX_PAGES = 10
REQUEST_TIMEOUT_SECONDS = 15
RUN_BUDGET_SECONDS = 60
SOURCE = "geckoterminal"

# GeckoTerminal venue ids that are launch platforms (confirmed against CoinGecko's launchpad list and the
# platforms' own sites). Everything else defaults to 'dex'. Unconfirmed names such as peach, lunya,
# arctide, aka-fun, minara-fun and virtuals-arc deliberately stay 'dex' until someone confirms them.
LAUNCHPAD_VENUES = {"argus", "faze", "foci", "o1-launchpad-arc", "long-supply"}


def venue_kind(dex_id: str) -> str:
    return "launchpad" if dex_id in LAUNCHPAD_VENUES else "dex"


def _num(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) and f >= 0 else None


def parse_pool(item: dict):
    """-> {'dex_id', 'name', 'volume'} or None when the pool carries no venue."""
    if not isinstance(item, dict):
        return None
    dex = (((item.get("relationships") or {}).get("dex") or {}).get("data") or {}).get("id")
    if not isinstance(dex, str) or not dex.strip():
        return None
    attrs = item.get("attributes") or {}
    volume = _num((attrs.get("volume_usd") or {}).get("h24")) or 0.0
    return {"dex_id": dex.strip().lower(), "name": str(attrs.get("name") or "?")[:80], "volume": volume}


def aggregate(pools: list, names: dict) -> list:
    """Per-venue rows. Every venue GeckoTerminal lists is included (zero volume if none of the sampled pools
    belong to it); a venue seen only in pools falls back to its id as its name."""
    per = {}
    for p in pools:
        row = per.setdefault(p["dex_id"], {"volume": 0.0, "active": 0, "top_name": None, "top_volume": 0.0})
        row["volume"] += p["volume"]
        if p["volume"] > 0:
            row["active"] += 1
        if p["volume"] > row["top_volume"]:
            row["top_name"], row["top_volume"] = p["name"], p["volume"]
    out = []
    for dex_id in sorted(set(per) | set(names)):
        agg = per.get(dex_id, {"volume": 0.0, "active": 0, "top_name": None, "top_volume": 0.0})
        out.append({
            "dex_id": dex_id,
            "name": names.get(dex_id) or dex_id,
            "kind": venue_kind(dex_id),
            "volume_24h_usd": round(agg["volume"], 2),
            "active_pools": agg["active"],
            "sample_pools": len(pools),
            "top_pool_name": agg["top_name"],
            "top_pool_volume_usd": round(agg["top_volume"], 2) if agg["top_name"] else None,
            "source": SOURCE,
        })
    return out


def _get(url, api_key, params=None):
    try:
        resp = requests.get(url, params=params, headers={"x-cg-pro-api-key": api_key, "Accept": "application/json"},
                            timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException:
        return 0, None
    if resp.status_code != 200:
        return resp.status_code, None
    try:
        return 200, resp.json()
    except ValueError:
        return 200, None


def fetch_dex_names(api_key: str):
    """(status, {dex_id: display name})."""
    status, payload = _get(DEXES_URL.format(network=NETWORK), api_key)
    if status != 200 or not isinstance(payload, dict):
        return status, {}
    return 200, {d["id"].lower(): (d.get("attributes") or {}).get("name") or d["id"]
                 for d in payload.get("data") or [] if isinstance(d, dict) and isinstance(d.get("id"), str)}


def fetch_pools_page(page: int, api_key: str, sort: str | None = SORT):
    params = {"page": page}
    if sort:
        params["sort"] = sort
    return _get(POOLS_URL.format(network=NETWORK), api_key, params)


def collect_pools(api_key: str, fetch=fetch_pools_page, clock=time.monotonic, budget_seconds: float = RUN_BUDGET_SECONDS):
    """-> (pools, summary). summary['complete'] is True only for a scan that ended naturally."""
    started = clock()
    pools, summary = [], {"pages": 0, "stopped": None, "complete": False, "sorted": True}
    sort = SORT
    for page in range(1, MAX_PAGES + 1):
        if clock() - started >= budget_seconds:
            summary["stopped"] = "time_budget"
            return pools, summary
        status, payload = fetch(page, api_key, sort)
        if page == 1 and status in (400, 422) and sort:       # the API rejected the sort parameter: retry plain
            sort, summary["sorted"] = None, False
            status, payload = fetch(page, api_key, None)
        summary["pages"] += 1
        if status == 429:
            summary["stopped"] = "rate_limited"
            return pools, summary
        if status != 200 or not isinstance(payload, dict):
            summary["stopped"] = f"http_{status}"
            return pools, summary
        parsed = [p for p in (parse_pool(i) for i in payload.get("data") or []) if p]
        if not (payload.get("data") or []):
            summary.update(stopped="no_more_pools", complete=True)
            return pools, summary
        pools.extend(parsed)
        if sort and parsed and parsed[-1]["volume"] == 0:        # sorted by volume: everything after is dust
            summary.update(stopped="volume_tail_reached", complete=True)
            return pools, summary
    summary.update(stopped="page_cap", complete=True)
    return pools, summary


def refresh_venues(client, api_key: str, fetch_names=fetch_dex_names, fetch_page=fetch_pools_page,
                   clock=time.monotonic) -> dict:
    started = clock()
    _, names = fetch_names(api_key)                      # names are cosmetic: a failure just falls back to ids
    pools, scan = collect_pools(api_key, fetch=fetch_page, clock=clock)
    summary = {"pages": scan["pages"], "pools": len(pools), "stopped": scan["stopped"], "written": 0,
               "total_volume_usd": round(sum(p["volume"] for p in pools), 2), "seconds": round(clock() - started, 1)}
    if not scan["complete"] or not pools:
        return summary                                   # an incomplete scan would understate everything
    stamp = datetime.now(timezone.utc).isoformat()
    rows = aggregate(pools, names)
    for r in rows:
        r["fetched_at"] = stamp
    client.table("venue_market_data").upsert(rows, on_conflict="dex_id").execute()
    summary["written"] = len(rows)
    return summary


def run_venues_refresh() -> dict:
    api_key = os.environ.get("COINGECKO_PRO_API_KEY")
    if not api_key:
        return {"skipped": "COINGECKO_PRO_API_KEY not set"}
    from db import get_client  # lazy: keeps this module importable without supabase env

    return refresh_venues(get_client(), api_key)
