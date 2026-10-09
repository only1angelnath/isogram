"""
market_data.py - hourly refresh of third-party market data (price, FDV, liquidity).

Source: GeckoTerminal via CoinGecko's onchain API (pro endpoint; the keyless endpoint
now answers 401). This is the ONE non-chain data source for project metrics, so it is
stored apart (token_market_data), labelled with its source, and timestamped; readers
hide rows that have gone stale (see docs/decisions/ADR-005).

Scope: the primary contract of every token / stablecoin project (the same segments
ADR-004 gives no score and no TVL). DeFi protocols are not priced here.

Safety: runs after ingestion and discovery in worker.main(), wrapped like discovery so
it can never fail (and so un-chain) the job. It also bounds itself: a per-request
timeout and a total time budget, so a slow API cannot delay the next run's start.

Rows GeckoTerminal does not return (no indexed pool) are left untouched, never zeroed.
"""

import math
import os
import time
from datetime import datetime, timezone

import requests

NETWORK = "arc"
GECKO_MULTI_URL = "https://pro-api.coingecko.com/api/v3/onchain/networks/{network}/tokens/multi/{addresses}"
BATCH_SIZE = 30                 # the documented cap for non-Analyst plans
REQUEST_TIMEOUT_SECONDS = 15
RUN_BUDGET_SECONDS = 120
SOURCE = "geckoterminal"
PAGE_SIZE = 1000                # PostgREST's default response cap

# category -> segment 'token' or 'stablecoin' in scoring/segments.py and
# api/aggregate.py (tests/test_market_data.py fails if this drifts from segments.py).
PRICED_CATEGORIES = {"token", "meme", "wrapped", "stablecoin", "institutional"}


def _num(value):
    """float for a finite, non-negative number; None for anything else (null, '', NaN, junk)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f >= 0 else None


def parse_token_rows(payload: dict) -> dict:
    """GeckoTerminal multi-token payload -> {lowercased_address: row for token_market_data}.
    A price of 0 is treated as 'no price' (a pool with nothing in it), never stored as 0."""
    rows = {}
    for item in (payload or {}).get("data") or []:
        attrs = item.get("attributes") or {}
        address = (attrs.get("address") or "").strip().lower()
        if not address:
            continue
        price = _num(attrs.get("price_usd"))
        coin_id = attrs.get("coingecko_coin_id")
        rows[address] = {
            "contract_address": address,
            "symbol": attrs.get("symbol"),
            "coingecko_coin_id": coin_id.strip() if isinstance(coin_id, str) and coin_id.strip() else None,
            "price_usd": price if price else None,
            "fdv_usd": _num(attrs.get("fdv_usd")),
            "market_cap_usd": _num(attrs.get("market_cap_usd")),
            "liquidity_usd": _num(attrs.get("total_reserve_in_usd")),
            "volume_24h_usd": _num((attrs.get("volume_usd") or {}).get("h24")),
            "source": SOURCE,
        }
    return rows


def collect_targets(project_rows: list) -> list:
    """Primary (first) contract of each priced-category project; lowercased, de-duplicated,
    original order kept. Pure function so it is testable without a database."""
    seen, out = set(), []
    for row in project_rows:
        if (row.get("category") or "").strip().lower() not in PRICED_CATEGORIES:
            continue
        contracts = row.get("contracts") or []
        if not contracts:
            continue
        address = contracts[0].strip().lower()
        if address and address not in seen:
            seen.add(address)
            out.append(address)
    return out


def load_target_addresses(client) -> list:
    """Keyset-paginated read of projects (PostgREST silently caps unpaginated reads at 1000)."""
    rows, last_id = [], None
    while True:
        query = client.table("projects").select("id, category, contracts")
        if last_id is not None:
            query = query.gt("id", last_id)
        page = query.order("id").limit(PAGE_SIZE).execute().data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        last_id = page[-1]["id"]
    return collect_targets(rows)


def fetch_batch(addresses: list, api_key: str):
    """One multi-token call. Returns (http_status, payload_or_None); status 0 = network error."""
    url = GECKO_MULTI_URL.format(network=NETWORK, addresses=",".join(addresses))
    try:
        resp = requests.get(
            url,
            headers={"x-cg-pro-api-key": api_key, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        return 0, None
    if resp.status_code != 200:
        return resp.status_code, None
    try:
        return 200, resp.json()
    except ValueError:
        return 200, None


def refresh_market_data(client, addresses: list, api_key: str, fetch=fetch_batch,
                        clock=time.monotonic, budget_seconds: float = RUN_BUDGET_SECONDS) -> dict:
    """Fetch in batches and upsert what comes back. Never raises on API trouble: a failed
    batch is skipped, a 429 or an exhausted time budget stops the run with what we have."""
    started = clock()
    summary = {"targets": len(addresses), "batches": 0, "returned": 0, "upserted": 0, "stopped": None}
    for i in range(0, len(addresses), BATCH_SIZE):
        if clock() - started >= budget_seconds:
            summary["stopped"] = "time_budget"
            break
        batch = addresses[i:i + BATCH_SIZE]
        status, payload = fetch(batch, api_key)
        summary["batches"] += 1
        if status == 429:
            summary["stopped"] = "rate_limited"
            break
        if status != 200 or payload is None:
            continue
        requested = set(batch)
        wanted = [r for addr, r in parse_token_rows(payload).items() if addr in requested]
        summary["returned"] += len(wanted)
        if not wanted:
            continue
        stamp = datetime.now(timezone.utc).isoformat()
        for r in wanted:
            r["fetched_at"] = stamp
        client.table("token_market_data").upsert(wanted, on_conflict="contract_address").execute()
        summary["upserted"] += len(wanted)
    return summary


def run_market_data_refresh() -> dict:
    """Entry point used by worker.main(). Skips quietly when no key is configured."""
    api_key = os.environ.get("COINGECKO_PRO_API_KEY")
    if not api_key:
        return {"skipped": "COINGECKO_PRO_API_KEY not set"}
    from db import get_client  # lazy: keeps this module importable without supabase env

    client = get_client()
    return refresh_market_data(client, load_target_addresses(client), api_key)
