"""
holders.py - holder counts for token, stablecoin and launchpad-token projects.

Source: Arc's own explorer (Blockscout), GET /api/v2/tokens/{address} -> holders_count. Free and
keyless, but the explorer sits behind a bot filter that rejects the default python-requests
user agent (see discovery.py), so a browser-like UA is sent.

Runs after the price refresh in worker.main(), wrapped like discovery and market data so it can
never fail or delay the job: bounded by a per-request timeout, a per-run call cap and a total
time budget. Addresses are refreshed oldest-first, never-fetched first, at most every 12 hours;
a 404 (the explorer does not index the address as a token) is cached as holders_count = NULL so
mass-produced clones do not eat the budget on every run.
"""

import time
from datetime import datetime, timedelta, timezone

import requests

EXPLORER_TOKEN_URL = "https://explorer.arc.io/api/v2/tokens/{address}"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36", "Accept": "application/json"}
SOURCE = "explorer.arc.io"
REQUEST_TIMEOUT_SECONDS = 15
RUN_BUDGET_SECONDS = 90
MAX_CALLS_PER_RUN = 150
PAUSE_SECONDS = 0.1             # be polite to a public explorer
REFRESH_AFTER = timedelta(hours=12)
PAGE_SIZE = 1000


def parse_holders(payload):
    """int >= 0 from the explorer's holders_count (it sends a number or a numeric string); else None."""
    value = payload.get("holders_count") if isinstance(payload, dict) else None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def fetch_token(address: str):
    """(http_status, payload_or_None); status 0 = network error."""
    try:
        resp = requests.get(EXPLORER_TOKEN_URL.format(address=address), headers=HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException:
        return 0, None
    if resp.status_code != 200:
        return resp.status_code, None
    try:
        return 200, resp.json()
    except ValueError:
        return 200, None


def load_state(client) -> dict:
    """{contract_address: fetched_at ISO string} for every stored row."""
    state, last = {}, None
    while True:
        query = client.table("token_holders").select("contract_address, fetched_at")
        if last is not None:
            query = query.gt("contract_address", last)
        page = query.order("contract_address").limit(PAGE_SIZE).execute().data or []
        for row in page:
            state[row["contract_address"]] = row.get("fetched_at")
        if len(page) < PAGE_SIZE:
            return state
        last = page[-1]["contract_address"]


def pick_due(targets: list, state: dict, now: datetime, limit: int = MAX_CALLS_PER_RUN,
             refresh_after: timedelta = REFRESH_AFTER) -> list:
    """Targets never fetched or older than refresh_after: never-fetched first, then oldest first, capped."""
    due = []
    for address in dict.fromkeys(targets):
        raw, fetched = state.get(address), None
        if raw:
            try:
                fetched = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if fetched.tzinfo is None:
                    fetched = fetched.replace(tzinfo=timezone.utc)
            except ValueError:
                fetched = None
        if fetched is None or now - fetched >= refresh_after:
            due.append((fetched or datetime.min.replace(tzinfo=timezone.utc), address))
    due.sort()
    return [address for _, address in due[:limit]]


def refresh_holders(client, candidates: list, fetch=fetch_token, clock=time.monotonic, sleep=time.sleep,
                    budget_seconds: float = RUN_BUDGET_SECONDS, pause: float = PAUSE_SECONDS) -> dict:
    """One call per candidate. 200 -> store the count (NULL if the payload has none); 404 -> cache NULL;
    429 or the time budget ends the pass; anything else (timeouts, 5xx) is skipped and retried next run."""
    started = clock()
    summary = {"due": len(candidates), "calls": 0, "updated": 0, "unindexed": 0, "stopped": None}
    for address in candidates:
        if clock() - started >= budget_seconds:
            summary["stopped"] = "time_budget"
            break
        status, payload = fetch(address)
        summary["calls"] += 1
        if status == 429:
            summary["stopped"] = "rate_limited"
            break
        if status == 200:
            count = parse_holders(payload)
        elif status == 404:
            count = None
        else:
            sleep(pause)
            continue
        client.table("token_holders").upsert(
            {"contract_address": address, "holders_count": count, "source": SOURCE,
             "fetched_at": datetime.now(timezone.utc).isoformat()},
            on_conflict="contract_address",
        ).execute()
        summary["updated" if count is not None else "unindexed"] += 1
        sleep(pause)
    return summary


def run_holders_refresh() -> dict:
    """Entry point used by worker.main()."""
    from db import get_client  # lazy: keeps this module importable without supabase env
    from market_data import load_target_addresses

    client = get_client()
    targets = load_target_addresses(client)
    due = pick_due(targets, load_state(client), datetime.now(timezone.utc))
    result = refresh_holders(client, due)
    result["targets"] = len(targets)
    return result
