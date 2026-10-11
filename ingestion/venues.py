"""
venues.py - per-venue (DEX / launchpad) 24h volume on Arc, from GeckoTerminal.

GeckoTerminal tags every pool with the venue ("dex") that hosts it; Arc has ~22, including launch
platforms (argus, faze, foci, ...). Each venue's own pools are read, busiest first (<= MAX_PAGES_PER_VENUE
pages of 20), and volume is summed per venue. Uniswap V2, V3 and V4 stay separate venues, as GeckoTerminal
and CoinGecko list them.

Anomaly filter. Raw sums are not trustworthy on Arc: on 2026-10-09 Uniswap V4 summed to $21.7M against
$0.4M on CoinGecko, because a few pools reported huge volume from 2-3 wallets (average trade ~$500k) and
~90 tiny pools reported volume dozens of times their reserves. A pool is EXCLUDED from the venue's volume if
  - it has fewer than MIN_TRADERS traders in 24h (buyers + sellers), or
  - its 24h volume exceeds MAX_TURNOVER x its reserves (or it has volume but no reserves).
Excluded volume is stored and shown next to the venue, never hidden. CoinGecko's own rule is not public;
these thresholds reconcile the two on 2026-10-09 data (check with ops/venue_preview.py before changing).

A venue is written only when ITS scan finished (pages ran out, volume tail hit zero, or the page cap was
reached - flagged `truncated` when volume was still non-zero there). Errors, a 429 or the time budget leave
unfinished venues' previous rows untouched. If GeckoTerminal stops sending transaction counts the scan is
refused rather than silently reporting unfiltered volume.

Runs after the other refreshes in worker.main(), wrapped like them: it can never fail the job.
"""

import os
import time
from datetime import datetime, timezone

import requests

NETWORK = "arc"
GECKO = "https://pro-api.coingecko.com/api/v3/onchain"
DEXES_URL = GECKO + "/networks/{network}/dexes"
VENUE_POOLS_URL = GECKO + "/networks/{network}/dexes/{dex}/pools"
SORT = "h24_volume_usd_desc"
MAX_PAGES_PER_VENUE = 10
REQUEST_TIMEOUT_SECONDS = 15
RUN_BUDGET_SECONDS = 120
SOURCE = "geckoterminal"

MIN_TRADERS = 10
MAX_TURNOVER = 25.0

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


def parse_pool(item: dict, dex_id: str | None = None):
    """-> {'dex_id', 'name', 'volume', 'reserve', 'traders'} or None without a venue. `traders` is None when
    GeckoTerminal sent no buyer/seller counts (buyers + sellers over-counts a wallet that did both, which only
    makes the filter slightly more lenient)."""
    if not isinstance(item, dict):
        return None
    dex = dex_id or (((item.get("relationships") or {}).get("dex") or {}).get("data") or {}).get("id")
    if not isinstance(dex, str) or not dex.strip():
        return None
    attrs = item.get("attributes") or {}
    h24 = ((attrs.get("transactions") or {}).get("h24")) or {}
    buyers, sellers = _num(h24.get("buyers")), _num(h24.get("sellers"))
    return {
        "dex_id": dex.strip().lower(),
        "name": str(attrs.get("name") or "?")[:80],
        "volume": _num((attrs.get("volume_usd") or {}).get("h24")) or 0.0,
        "reserve": _num(attrs.get("reserve_in_usd")) or 0.0,
        "traders": int(buyers + sellers) if buyers is not None and sellers is not None else None,
    }


def classify_pool(p: dict, min_traders: int = MIN_TRADERS, max_turnover: float = MAX_TURNOVER) -> str:
    """'kept' | 'excluded' | 'unknown' (no transaction counts, so the filter cannot judge it)."""
    if p["volume"] <= 0:
        return "kept"                                    # no volume: nothing to include or exclude
    if p["traders"] is None:
        return "unknown"
    if p["traders"] < min_traders:
        return "excluded"
    if p["reserve"] <= 0 or p["volume"] > max_turnover * p["reserve"]:
        return "excluded"
    return "kept"


def aggregate(pools: list, names: dict, scanned: dict | None = None, min_traders: int = MIN_TRADERS,
              max_turnover: float = MAX_TURNOVER) -> list:
    """Per-venue rows for every venue in `scanned` ({dex_id: {'truncated': bool}}; defaults to the venues
    present in pools). 'unknown' pools are left out of the volume and counted as excluded."""
    scanned = scanned if scanned is not None else {d: {"truncated": False} for d in {p["dex_id"] for p in pools}}
    out = []
    for dex_id in sorted(scanned):
        mine = [p for p in pools if p["dex_id"] == dex_id]
        kept_vol = excl_vol = 0.0
        active = excl_n = 0
        top_name, top_vol = None, 0.0
        for p in mine:
            state = classify_pool(p, min_traders, max_turnover)
            if state == "kept":
                kept_vol += p["volume"]
                if p["volume"] > 0:
                    active += 1
                if p["volume"] > top_vol:
                    top_name, top_vol = p["name"], p["volume"]
            else:
                excl_vol += p["volume"]
                excl_n += 1
        out.append({
            "dex_id": dex_id,
            "name": names.get(dex_id) or dex_id,
            "kind": venue_kind(dex_id),
            "volume_24h_usd": round(kept_vol, 2),
            "active_pools": active,
            "sample_pools": len(mine),
            "excluded_volume_usd": round(excl_vol, 2),
            "excluded_pools": excl_n,
            "truncated": bool(scanned[dex_id].get("truncated")),
            "top_pool_name": top_name,
            "top_pool_volume_usd": round(top_vol, 2) if top_name else None,
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
    """(status, {dex_id: display name}) - this also enumerates the venues to scan."""
    status, payload = _get(DEXES_URL.format(network=NETWORK), api_key)
    if status != 200 or not isinstance(payload, dict):
        return status, {}
    return 200, {d["id"].lower(): (d.get("attributes") or {}).get("name") or d["id"]
                 for d in payload.get("data") or [] if isinstance(d, dict) and isinstance(d.get("id"), str)}


def fetch_venue_page(dex_id: str, page: int, api_key: str, sort: str | None = SORT):
    params = {"page": page}
    if sort:
        params["sort"] = sort
    return _get(VENUE_POOLS_URL.format(network=NETWORK, dex=dex_id), api_key, params)


def scan_venue(dex_id: str, api_key: str, fetch=fetch_venue_page, sort: str | None = SORT, max_pages: int = MAX_PAGES_PER_VENUE):
    """-> (pools, outcome) where outcome is {'status': 'complete'|'error'|'rate_limited', 'truncated': bool,
    'calls': n, 'sorted': bool}. A venue with no pools at all is complete with zero pools."""
    pools, calls = [], 0
    for page in range(1, max_pages + 1):
        status, payload = fetch(dex_id, page, api_key, sort)
        calls += 1
        if status in (400, 422) and sort and page == 1:       # the API rejected the sort parameter: go unsorted
            sort = None
            status, payload = fetch(dex_id, page, api_key, None)
            calls += 1
        if status == 429:
            return pools, {"status": "rate_limited", "truncated": False, "calls": calls, "sorted": sort is not None}
        if status != 200 or not isinstance(payload, dict):
            return pools, {"status": "error", "truncated": False, "calls": calls, "sorted": sort is not None}
        items = payload.get("data") or []
        if not items:
            return pools, {"status": "complete", "truncated": False, "calls": calls, "sorted": sort is not None}
        parsed = [p for p in (parse_pool(i, dex_id) for i in items) if p]
        pools.extend(parsed)
        if sort and parsed and parsed[-1]["volume"] == 0:      # sorted by volume: everything after is dust
            return pools, {"status": "complete", "truncated": False, "calls": calls, "sorted": True}
    last_volume = pools[-1]["volume"] if pools else 0
    return pools, {"status": "complete", "truncated": bool(sort is None or last_volume > 0), "calls": calls, "sorted": sort is not None}


def refresh_venues(client, api_key: str, fetch_names=fetch_dex_names, fetch_page=fetch_venue_page,
                   clock=time.monotonic, budget_seconds: float = RUN_BUDGET_SECONDS) -> dict:
    started = clock()
    status, names = fetch_names(api_key)
    summary = {"venues": len(names), "written": 0, "incomplete": [], "pools": 0, "calls": 0, "kept_usd": 0.0,
               "excluded_usd": 0.0, "stopped": None, "seconds": 0.0}
    if not names:
        summary["stopped"] = f"venue_list_http_{status}"
        return summary
    pools, scanned = [], {}
    for dex_id in sorted(names):
        if clock() - started >= budget_seconds:
            summary["stopped"] = "time_budget"
            break
        venue_pools, outcome = scan_venue(dex_id, api_key, fetch=fetch_page)
        summary["calls"] += outcome["calls"]
        if outcome["status"] == "rate_limited":
            summary["stopped"] = "rate_limited"
            break
        if outcome["status"] != "complete":
            summary["incomplete"].append(dex_id)             # keep its previous row; try again next run
            continue
        if any(p["volume"] > 0 for p in venue_pools) and all(p["traders"] is None for p in venue_pools if p["volume"] > 0):
            summary["incomplete"].append(dex_id)             # no transaction counts: cannot filter, refuse to guess
            continue
        pools.extend(venue_pools)
        scanned[dex_id] = {"truncated": outcome["truncated"]}
    rows = aggregate(pools, names, scanned)
    stamp = datetime.now(timezone.utc).isoformat()
    for r in rows:
        r["fetched_at"] = stamp
    if rows:
        client.table("venue_market_data").upsert(rows, on_conflict="dex_id").execute()
    summary.update(written=len(rows), pools=len(pools),
                   kept_usd=round(sum(r["volume_24h_usd"] for r in rows), 2),
                   excluded_usd=round(sum(r["excluded_volume_usd"] for r in rows), 2),
                   seconds=round(clock() - started, 1))
    return summary


def run_venues_refresh() -> dict:
    api_key = os.environ.get("COINGECKO_PRO_API_KEY")
    if not api_key:
        return {"skipped": "COINGECKO_PRO_API_KEY not set"}
    from db import get_client  # lazy: keeps this module importable without supabase env

    return refresh_venues(get_client(), api_key)
