"""
socials.py - self-reported social links for token, stablecoin and launchpad-token projects.

Source: GeckoTerminal token info (GET .../tokens/{address}/info): websites, twitter_handle, telegram_handle,
discord_url. These are registered by whoever deployed the token and are NOT verified, so this module only
trims and length-caps them; the API re-validates every link before the dashboard may render it.

Bounded like the other optional refreshes (holders.py): per-request timeout, per-run call cap and a time
budget; addresses are refreshed oldest-first, never-fetched first, at most every 7 days; a 404 or an empty
answer is cached as an all-NULL row so tokens without links are not re-queried every run. It runs after the
other refreshes in worker.main() and can never fail the job.
"""

import re
import time
from datetime import datetime, timedelta, timezone

import requests

GECKO_INFO_URL = "https://pro-api.coingecko.com/api/v3/onchain/networks/{network}/tokens/{address}/info"
NETWORK = "arc"
SOURCE = "geckoterminal"
REQUEST_TIMEOUT_SECONDS = 15
RUN_BUDGET_SECONDS = 60
MAX_CALLS_PER_RUN = 60
PAUSE_SECONDS = 0.1
REFRESH_AFTER = timedelta(days=7)
PAGE_SIZE = 1000
MAX_LEN = 300
_CONTROL = re.compile(r"[\x00-\x1f\x7f\s]")      # whitespace and control characters never belong in a link or handle


def clean(value):
    """A trimmed string of at most MAX_LEN characters with no whitespace/control characters, else None."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    return v if v and len(v) <= MAX_LEN and not _CONTROL.search(v) else None


def parse_info(payload) -> dict:
    """GeckoTerminal token-info payload -> {'website', 'twitter', 'telegram', 'discord'} (each str or None)."""
    attrs = ((payload or {}).get("data") or {}).get("attributes") if isinstance(payload, dict) else None
    attrs = attrs if isinstance(attrs, dict) else {}
    websites = attrs.get("websites")
    website = next((w for w in (clean(x) for x in websites) if w), None) if isinstance(websites, list) else None
    return {
        "website": website,
        "twitter": clean(attrs.get("twitter_handle")),
        "telegram": clean(attrs.get("telegram_handle")),
        "discord": clean(attrs.get("discord_url")),
    }


def fetch_info(address: str, api_key: str):
    """(http_status, payload_or_None); status 0 = network error."""
    try:
        resp = requests.get(GECKO_INFO_URL.format(network=NETWORK, address=address),
                            headers={"x-cg-pro-api-key": api_key, "Accept": "application/json"},
                            timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException:
        return 0, None
    if resp.status_code != 200:
        return resp.status_code, None
    try:
        return 200, resp.json()
    except ValueError:
        return 200, None


def load_state(client) -> dict:
    state, last = {}, None
    while True:
        query = client.table("token_socials").select("contract_address, fetched_at")
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


def refresh_socials(client, candidates: list, api_key: str, fetch=fetch_info, clock=time.monotonic,
                    sleep=time.sleep, budget_seconds: float = RUN_BUDGET_SECONDS, pause: float = PAUSE_SECONDS) -> dict:
    """200 -> store what was parsed (all NULL if nothing); 404 -> all-NULL row; 429 or the time budget ends the
    pass; anything else (timeouts, 5xx) is skipped and retried next run."""
    started = clock()
    summary = {"due": len(candidates), "calls": 0, "with_links": 0, "empty": 0, "stopped": None}
    for address in candidates:
        if clock() - started >= budget_seconds:
            summary["stopped"] = "time_budget"
            break
        status, payload = fetch(address, api_key)
        summary["calls"] += 1
        if status == 429:
            summary["stopped"] = "rate_limited"
            break
        if status == 200:
            links = parse_info(payload)
        elif status == 404:
            links = parse_info(None)
        else:
            sleep(pause)
            continue
        client.table("token_socials").upsert(
            {"contract_address": address, **links, "source": SOURCE, "fetched_at": datetime.now(timezone.utc).isoformat()},
            on_conflict="contract_address",
        ).execute()
        summary["with_links" if any(links.values()) else "empty"] += 1
        sleep(pause)
    return summary


def run_socials_refresh() -> dict:
    import os

    api_key = os.environ.get("COINGECKO_PRO_API_KEY")
    if not api_key:
        return {"skipped": "COINGECKO_PRO_API_KEY not set"}
    from db import get_client  # lazy: keeps this module importable without supabase env
    from market_data import load_target_addresses

    client = get_client()
    targets = load_target_addresses(client)
    due = pick_due(targets, load_state(client), datetime.now(timezone.utc))
    result = refresh_socials(client, due, api_key)
    result["targets"] = len(targets)
    return result
