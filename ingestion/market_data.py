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
from datetime import datetime, timedelta, timezone

import requests

NETWORK = "arc"
GECKO_MULTI_URL = "https://pro-api.coingecko.com/api/v3/onchain/networks/{network}/tokens/multi/{addresses}"
GECKO_OHLCV_URL = "https://pro-api.coingecko.com/api/v3/onchain/networks/{network}/tokens/{address}/ohlcv/day"
BATCH_SIZE = 30                 # the documented cap for non-Analyst plans
REQUEST_TIMEOUT_SECONDS = 15
RUN_BUDGET_SECONDS = 150        # shared by the price refresh and the 7d-volume pass
VOLUME_7D_DAYS = 7              # last 7 UTC days, today's partial candle included
VOLUME_7D_MAX_CALLS_PER_RUN = 80
VOLUME_7D_REFRESH_AFTER = timedelta(hours=6)
SOURCE = "geckoterminal"
PAGE_SIZE = 1000                # PostgREST's default response cap

# category -> segment 'token', 'stablecoin' or 'launchpad' in scoring/segments.py and
# api/aggregate.py (tests/test_market_data.py fails if this drifts from segments.py). A launchpad
# row's FIRST contract is its own token (e.g. ARGUS), which is what gets priced.
PRICED_CATEGORIES = {"token", "meme", "wrapped", "stablecoin", "institutional", "launchpad"}


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
                        clock=time.monotonic, budget_seconds: float = RUN_BUDGET_SECONDS,
                        priced_out: list | None = None) -> dict:
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
        if priced_out is not None:
            priced_out.extend(r["contract_address"] for r in wanted if r["price_usd"])
        if not wanted:
            continue
        stamp = datetime.now(timezone.utc).isoformat()
        for r in wanted:
            r["fetched_at"] = stamp
        client.table("token_market_data").upsert(wanted, on_conflict="contract_address").execute()
        summary["upserted"] += len(wanted)
    return summary


def fetch_ohlcv_day(address: str, api_key: str):
    """Daily candles for the token's most liquid pool. Returns (http_status, payload_or_None)."""
    url = GECKO_OHLCV_URL.format(network=NETWORK, address=address)
    try:
        resp = requests.get(
            url,
            params={"aggregate": 1, "limit": VOLUME_7D_DAYS + 3, "currency": "usd"},
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


def volume_from_ohlcv(payload: dict, now: datetime | None = None, days: int = VOLUME_7D_DAYS):
    """Sum of candle volumes over the last `days` UTC days (today included), or None if the payload
    is unusable. Days with no swaps are simply absent from the API's list, so absence = 0 volume;
    candles older than the window must be dropped because `limit` counts candles, not days."""
    attrs = ((payload or {}).get("data") or {}).get("attributes")
    if not isinstance(attrs, dict) or not isinstance(attrs.get("ohlcv_list"), list):
        return None
    now = now or datetime.now(timezone.utc)
    window_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) - timedelta(days=days - 1)
    total = 0.0
    for candle in attrs["ohlcv_list"]:
        if not isinstance(candle, (list, tuple)) or len(candle) < 6:
            continue
        try:
            ts = datetime.fromtimestamp(int(candle[0]), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        volume = _num(candle[5])
        if ts >= window_start and volume is not None:
            total += volume
    return total


def load_volume_state(client) -> dict:
    """{contract_address: volume_7d_fetched_at ISO string or None} for every stored token."""
    state, last = {}, None
    while True:
        query = client.table("token_market_data").select("contract_address, volume_7d_fetched_at")
        if last is not None:
            query = query.gt("contract_address", last)
        page = query.order("contract_address").limit(PAGE_SIZE).execute().data or []
        for row in page:
            state[row["contract_address"]] = row.get("volume_7d_fetched_at")
        if len(page) < PAGE_SIZE:
            return state
        last = page[-1]["contract_address"]


def pick_volume_candidates(priced: list, state: dict, now: datetime, limit: int = VOLUME_7D_MAX_CALLS_PER_RUN) -> list:
    """Priced tokens whose 7d volume is missing or older than VOLUME_7D_REFRESH_AFTER, never-fetched
    first, then oldest first, capped so one run cannot burn the whole API budget."""
    due = []
    for address in dict.fromkeys(priced):
        raw = state.get(address)
        fetched = None
        if raw:
            try:
                fetched = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if fetched.tzinfo is None:
                    fetched = fetched.replace(tzinfo=timezone.utc)
            except ValueError:
                fetched = None
        if fetched is None or now - fetched >= VOLUME_7D_REFRESH_AFTER:
            due.append((fetched or datetime.min.replace(tzinfo=timezone.utc), address))
    due.sort()
    return [address for _, address in due[:limit]]


def refresh_volume_7d(client, candidates: list, api_key: str, fetch=fetch_ohlcv_day, clock=time.monotonic,
                      started: float | None = None, budget_seconds: float = RUN_BUDGET_SECONDS) -> dict:
    """One OHLCV call per candidate. A token with no pool (404) or any error is skipped and
    keeps its old value; a 429 or the shared time budget ends the pass."""
    started = clock() if started is None else started
    summary = {"calls": 0, "updated": 0, "stopped": None}
    for address in candidates:
        if clock() - started >= budget_seconds:
            summary["stopped"] = "time_budget"
            break
        status, payload = fetch(address, api_key)
        summary["calls"] += 1
        if status == 429:
            summary["stopped"] = "rate_limited"
            break
        if status != 200:
            continue
        volume = volume_from_ohlcv(payload)
        if volume is None:
            continue
        client.table("token_market_data").upsert(
            {"contract_address": address, "volume_7d_usd": volume,
             "volume_7d_fetched_at": datetime.now(timezone.utc).isoformat()},
            on_conflict="contract_address",
        ).execute()
        summary["updated"] += 1
    return summary


def run_market_data_refresh() -> dict:
    """Entry point used by worker.main(). Skips quietly when no key is configured."""
    api_key = os.environ.get("COINGECKO_PRO_API_KEY")
    if not api_key:
        return {"skipped": "COINGECKO_PRO_API_KEY not set"}
    from db import get_client  # lazy: keeps this module importable without supabase env

    started = time.monotonic()
    client = get_client()
    priced: list = []
    result = refresh_market_data(client, load_target_addresses(client), api_key, priced_out=priced)
    if result["stopped"] == "rate_limited":
        return result
    try:
        candidates = pick_volume_candidates(priced, load_volume_state(client), datetime.now(timezone.utc))
        vol = refresh_volume_7d(client, candidates, api_key, started=started)
        result["volume_7d_updated"] = vol["updated"]
        result["volume_7d_calls"] = vol["calls"]
        result["stopped"] = result["stopped"] or vol["stopped"]
    except Exception as exc:  # the 7d pass must never take the price refresh down with it
        result["volume_7d_error"] = f"{type(exc).__name__}: {exc}"
    return result
