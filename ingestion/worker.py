"""
worker.py — main ingestion entrypoint.

Run once per invocation (intended for a GitHub Actions cron schedule, not a
long-running process — see docs/ARCHITECTURE.md §2.1). Each run:
  1. Reads the last-synced block from sync_state.
  2. Fetches new blocks from Arc mainnet directly via RPC.
  3. Decodes gas paid (native -> USDC view) and USDC/EURC/USYC Transfer events.
  4. Upserts everything into Supabase.
  5. Advances the checkpoint — only after the whole batch succeeds.

Usage:
    python worker.py
"""

import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

from db import (
    get_client,
    get_last_synced_block,
    load_contract_project_map,
    resolve_project_id,
    update_last_synced_block,
    upsert_gas_events,
    upsert_token_flows,
)
from decode import (
    calculate_gas_paid_usdc,
    decode_erc20_transfer_amount,
    is_native_sentinel,
)

ARC_MAINNET_RPC = os.environ.get("ARC_RPC_URL", "https://rpc.mainnet.arc.io")
ARC_CHAIN_ID = 5042

# --- RPC endpoint pool (2026-09-26) -----------------------------------------
#
# rpc.mainnet.arc.io (the free default/shared endpoint) confirmed 429s from
# GitHub Actions runners while the exact same request succeeded from a
# residential connection at the same moment — i.e. it's the *source IP*
# being throttled on that one shared endpoint, not a global outage or a
# problem with our request rate as such. Arc's own docs say plainly:
# "Default RPC URLs are shared and may be rate-limited... override with your
# own provider."
#
# So the pool now prefers dedicated, authenticated endpoints (each with its
# own individual quota, not shared with every other anonymous caller of
# Arc's public infra) and only falls back to the free shared mirrors as a
# last resort. Every RPC call rotates through the whole pool in order,
# trying the next endpoint only after the current one exhausts its own
# retry/backoff budget (see _call_on_pool below).
#
# Dedicated endpoint env vars (set as GitHub Actions secrets — NEVER commit
# an actual key/URL containing one to the repo):
#   ALCHEMY_ARC_RPC_URL      e.g. https://arc-mainnet.g.alchemy.com/v2/<key>
#   DRPC_ARC_RPC_URL         e.g. https://lb.drpc.live/arc/<key>
#   BLOCKDAEMON_ARC_RPC_URL  e.g. https://svc.blockdaemon.com/arc/mainnet/native
#   BLOCKDAEMON_API_KEY      sent as `Authorization: Bearer <key>` (Blockdaemon's
#                            key is not embedded in the URL, unlike the other two)
#   QUICKNODE_ARC_RPC_URL    e.g. https://<subdomain>.arc-mainnet.quiknode.pro/<token>/
# Any that aren't set are simply skipped — this all degrades gracefully to
# just the free mirrors if no keys are configured (e.g. running locally
# without the secrets exported).
#
# ARC_RPC_FALLBACK_URLS (comma-separated) overrides the free-mirror list if
# Arc adds/removes mirrors later. ARC_RPC_URL (the module-level default,
# rpc.mainnet.arc.io) is always included as one of the free-mirror fallbacks.
ARC_RPC_FALLBACK_URLS = [
    u.strip()
    for u in os.environ.get(
        "ARC_RPC_FALLBACK_URLS",
        "https://rpc.drpc.mainnet.arc.io,"
        "https://rpc.blockdaemon.mainnet.arc.io,"
        "https://rpc.quicknode.mainnet.arc.io",
    ).split(",")
    if u.strip()
]


def _dedicated_endpoint_specs() -> list:
    """
    Build the list of dedicated/authenticated endpoints from env vars, in
    preference order. Each entry is {"name", "url", "headers"} — headers is
    None for endpoints that embed their key in the URL itself (Alchemy,
    dRPC, QuickNode), or a dict for endpoints needing an auth header
    (Blockdaemon). Only endpoints with the required env var(s) actually set
    are included.
    """
    specs = []

    alchemy_url = os.environ.get("ALCHEMY_ARC_RPC_URL")
    if alchemy_url:
        specs.append({"name": "alchemy", "url": alchemy_url, "headers": None})

    drpc_url = os.environ.get("DRPC_ARC_RPC_URL")
    if drpc_url:
        specs.append({"name": "drpc-keyed", "url": drpc_url, "headers": None})

    blockdaemon_url = os.environ.get("BLOCKDAEMON_ARC_RPC_URL")
    blockdaemon_key = os.environ.get("BLOCKDAEMON_API_KEY")
    if blockdaemon_url and blockdaemon_key:
        specs.append({
            "name": "blockdaemon",
            "url": blockdaemon_url,
            "headers": {"Authorization": f"Bearer {blockdaemon_key}"},
        })
    elif blockdaemon_url or blockdaemon_key:
        print(
            "BLOCKDAEMON_ARC_RPC_URL and BLOCKDAEMON_API_KEY must both be set "
            "to use Blockdaemon — only one was found, skipping it.",
            file=sys.stderr,
        )

    quicknode_url = os.environ.get("QUICKNODE_ARC_RPC_URL")
    if quicknode_url:
        specs.append({"name": "quicknode-keyed", "url": quicknode_url, "headers": None})

    return specs

# Tracked tokens and their decimals (see docs/architecture_essentials.md).
# All three are the tokens seeded in the `projects` table by the initial
# migration (supabase/migrations/20260921114348_init_schema.sql) — a token's
# Transfer events are only worth decoding here once it's also a project we
# can attribute flows to, and once scoring/tvl.py can price it (see
# scoring/tvl.py's PRICED_TOKENS, which must stay in sync with this dict).
# EURC and USYC were seeded as projects from day one but were NOT actually
# being decoded here until now — TVL was silently USDC-only as a result.
# Extend this further as more projects/tokens are seeded into `projects`.
TRACKED_TOKENS = {
    "0x3600000000000000000000000000000000000000": {"symbol": "USDC", "decimals": 6},
    "0xbef5f6d51cb62b58e6a8f77868681825c6fe21c1": {"symbol": "EURC", "decimals": 6},
    "0x8a5d989bbb96929f689b0200f435f53da42bf490": {"symbol": "USYC", "decimals": 6},
}

# ERC-20 Transfer(address,address,uint256) event topic0.
TRANSFER_EVENT_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Default first-run start block. Deliberately recent, not genesis — Arc
# mainnet is only days old at time of writing, and starting at genesis on a
# healthy chain would be wasted work. Override with START_BLOCK env var.
DEFAULT_START_BLOCK = int(os.environ.get("START_BLOCK", "0"))

# Don't process more than this many blocks in one run — keeps each cron
# invocation bounded and limits how much work is lost if a run fails
# partway.
#
# RAISED 100 -> 3000 on 2026-09-26. GitHub's own `schedule:` trigger is
# best-effort and was observed firing ~3 hours apart instead of the
# configured */5 * * * * (a documented GitHub Actions limitation, not a
# bug in this workflow — scheduled triggers can be delayed under platform
# load, especially at tight intervals). At Arc's ~2 blocks/sec, a 3-hour
# gap is ~21,600 new blocks between runs; MAX_BLOCKS_PER_RUN=100 could
# never close that gap even with the RPC issues fully solved. 3000 is
# still bounded (won't blow past ingestion-cron.yml's timeout on a normal
# run) while making real progress against a multi-hour gap. Revisit once
# an external trigger (see AGENTS.md/HANDOFF.md) makes GitHub's scheduler
# unnecessary and the backlog is actually caught up.
MAX_BLOCKS_PER_RUN = int(os.environ.get("MAX_BLOCKS_PER_RUN", "3000"))

# usd_value is only populated for tokens we can currently price at 1:1 USD.
# EURC is EUR-pegged, not USD-pegged — pricing it at 1:1 USD here would be
# wrong in a way that's easy to miss downstream (scoring/tvl.py makes the
# same simplification deliberately and documents it; this dict does not,
# because a wrong per-transfer usd_value is worse than a missing one).
# USYC is USD-denominated but not necessarily exactly 1:1 in practice; treated
# as 1:1 for v1 alongside USDC, consistent with scoring/tvl.py's PRICED_TOKENS.
USD_PEGGED_1_TO_1 = {"USDC", "USYC"}

# --- RPC retry/backoff (docs/BUGS.md #4 — confirmed live 2026-09-26) -------
#
# Real production log, 2026-09-26T05:42:50Z and again at 08:34-08:38Z:
# requests.exceptions.HTTPError: 429, raised from w3.eth.get_transaction_receipt(),
# repeatedly, even after exponential backoff up to ~16s and even at
# RPC_CONCURRENCY=3. A same-moment curl from a residential IP against the
# same default endpoint returned 200 — confirming this is GitHub Actions'
# source IP being throttled on rpc.mainnet.arc.io specifically, not a global
# rate limit or outage. See the endpoint-pool comment above for the fix this
# drove (rotation across Arc's documented mirror endpoints).
#
# RPC_RETRY_MAX_ATTEMPTS: total attempts per call against ONE endpoint before
# moving on to the next endpoint in the pool (1 initial + N-1 retries).
# Deliberately small (2) now that rotation exists — better to fail fast on a
# throttled mirror and try the next one than to burn 16-30s backing off on a
# single endpoint that curl already told us is being rate-limited.
RPC_RETRY_MAX_ATTEMPTS = int(os.environ.get("RPC_RETRY_MAX_ATTEMPTS", "2"))
RPC_RETRY_BASE_DELAY_SECONDS = float(os.environ.get("RPC_RETRY_BASE_DELAY_SECONDS", "2"))
RPC_RETRY_MAX_DELAY_SECONDS = float(os.environ.get("RPC_RETRY_MAX_DELAY_SECONDS", "30"))
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _call_with_retry(fn, *args, max_attempts=None, **kwargs):
    """
    Call fn(*args, **kwargs), retrying on 429/5xx from the RPC endpoint with
    exponential backoff + jitter. Any other exception (or exhausting
    retries) propagates so the caller (typically _call_on_pool, see below)
    can move on to the next endpoint, or — if this is the last endpoint —
    so run()'s existing try/except can skip advancing the checkpoint.
    """
    attempts = max_attempts if max_attempts is not None else RPC_RETRY_MAX_ATTEMPTS
    last_exc = None
    for attempt in range(attempts):
        try:
            return fn(*args, **kwargs)
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status not in RETRYABLE_STATUS_CODES:
                raise
            last_exc = exc
            if attempt == attempts - 1:
                break

            retry_after = None
            if exc.response is not None:
                header = exc.response.headers.get("Retry-After")
                if header:
                    try:
                        retry_after = float(header)
                    except ValueError:
                        retry_after = None

            if retry_after is not None:
                delay = retry_after
            else:
                delay = min(
                    RPC_RETRY_MAX_DELAY_SECONDS,
                    RPC_RETRY_BASE_DELAY_SECONDS * (2 ** attempt),
                )
            delay += random.uniform(0, 0.5)  # jitter

            print(
                f"RPC call hit {status}, retrying in {delay:.1f}s "
                f"(attempt {attempt + 1}/{attempts})",
                file=sys.stderr,
            )
            time.sleep(delay)

    raise last_exc


class _StickyPoolIndex:
    """
    Tracks the last endpoint in the pool that actually worked, so
    subsequent calls try it FIRST instead of always restarting from index 0.
    Without this, if the first endpoint (e.g. Alchemy on a tight free-tier
    limit) is rate-limiting us for a whole run, EVERY single call — there
    can be thousands per run — pays the cost of failing on it before
    falling through to whichever endpoint actually works. Observed directly
    2026-09-26: a run that succeeded took 200s for 100 blocks, almost
    entirely spent on repeated 429s from the pool's first entry before each
    call fell through.

    Not thread-safe in a strict sense (multiple threads in
    fetch_receipts_concurrent's pool can race on .index), and deliberately
    not locked — worst case under a race is two threads briefly try the
    same stale index together, which costs at most one extra fallback
    step, not a correctness issue.
    """
    def __init__(self):
        self.index = 0


def _call_on_pool(pool: list, sticky: "_StickyPoolIndex", method_name: str, *args, **kwargs):
    """
    Try an eth_* call (by method name, e.g. "get_block") against each Web3
    in `pool`, starting from `sticky.index` (the last endpoint known to
    work) and wrapping around, rather than always starting at pool[0]. Each
    endpoint gets its own short retry/backoff budget via _call_with_retry;
    once that budget is exhausted for one endpoint, move to the next. On
    success, updates sticky.index so later calls start there too. Only
    raises once every endpoint in the pool has failed.
    """
    n = len(pool)
    start = sticky.index % n
    last_exc = None
    for offset in range(n):
        i = (start + offset) % n
        w3 = pool[i]
        fn = getattr(w3.eth, method_name)
        try:
            result = _call_with_retry(fn, *args, **kwargs)
            sticky.index = i
            return result
        except requests.exceptions.HTTPError as exc:
            last_exc = exc
            continue
    raise last_exc


def _block_number_on_pool(pool: list, sticky: "_StickyPoolIndex") -> int:
    """
    eth.block_number is a property, not a callable, so it can't go through
    _call_on_pool (which calls getattr(w3.eth, name)(*args, **kwargs)).
    Same sticky-rotation behavior, just wrapped in a zero-arg lambda per
    endpoint.
    """
    n = len(pool)
    start = sticky.index % n
    last_exc = None
    for offset in range(n):
        i = (start + offset) % n
        w3 = pool[i]
        try:
            result = _call_with_retry(lambda w3=w3: w3.eth.block_number)
            sticky.index = i
            return result
        except requests.exceptions.HTTPError as exc:
            last_exc = exc
            continue
    raise last_exc


def _as_pool(w3_or_pool) -> list:
    """
    Normalize a single Web3 instance or a list of them into a list, so
    process_block()/process_blocks_concurrent() work unchanged whether
    called with one connection (existing tests, get_web3()) or a real
    multi-endpoint pool (get_web3_pool(), used by run()).
    """
    return w3_or_pool if isinstance(w3_or_pool, list) else [w3_or_pool]


def get_web3() -> Web3:
    """Single-endpoint connection to the primary/default RPC URL."""
    w3 = Web3(Web3.HTTPProvider(ARC_MAINNET_RPC))
    if not w3.is_connected():
        raise RuntimeError(f"Could not connect to Arc mainnet RPC at {ARC_MAINNET_RPC}")
    return w3


def get_web3_pool() -> list:
    """
    Build the full RPC endpoint pool, preference order:
      1. Dedicated/authenticated endpoints (Alchemy, dRPC, Blockdaemon,
         QuickNode) — whichever are configured via env vars, each with its
         own individual quota.
      2. Free shared mirrors (ARC_RPC_URL / rpc.mainnet.arc.io plus
         ARC_RPC_FALLBACK_URLS) — last resort, since these are the ones
         confirmed to throttle GitHub Actions' source IP.
    Skips any endpoint that fails a basic connectivity check up front (bad
    key, wrong URL, endpoint down). Raises only if every single endpoint —
    dedicated and free — is unreachable.
    """
    specs = _dedicated_endpoint_specs()
    free_urls = [ARC_MAINNET_RPC] + [u for u in ARC_RPC_FALLBACK_URLS if u != ARC_MAINNET_RPC]
    specs += [{"name": url, "url": url, "headers": None} for url in free_urls]

    pool = []
    for spec in specs:
        try:
            request_kwargs = {"headers": spec["headers"]} if spec["headers"] else {}
            w3 = Web3(Web3.HTTPProvider(spec["url"], request_kwargs=request_kwargs))
            # is_connected() swallows the real error and just returns False —
            # confirmed live 2026-10-02: blockdaemon has failed this check
            # repeatedly with a key independently confirmed valid via curl,
            # and we had no way to see why. Doing a real eth_chainId call
            # instead surfaces the actual exception (e.g. an auth header
            # not making it through is_connected()'s lightweight probe in
            # this web3.py version, vs. a real network failure) so this is
            # diagnosable instead of a permanent silent guess.
            w3.eth.chain_id
            pool.append(w3)
        except Exception as exc:
            print(f"RPC endpoint failed connectivity check, skipping: {spec['name']} ({type(exc).__name__}: {exc})", file=sys.stderr)
    if not pool:
        tried = ", ".join(s["name"] for s in specs)
        raise RuntimeError(f"No Arc RPC endpoints reachable (tried: {tried})")
    return pool


def _decode_transaction(tx_hash, block_number, block_ts, to_address, gas_price_fallback, receipt, contract_project_map):
    """
    Shared decode logic for one (tx, receipt) pair — used by both
    process_block() (sequential, kept for backward compatibility / existing
    tests) and process_blocks_concurrent() (the docs/BUGS.md #5 fix, see
    below). Extracted so there is exactly one copy of this correctness-
    critical logic (docs/BUGS.md #1) rather than two that could drift.
    Returns (gas_event: dict | None, token_flows: list[dict]).
    """
    gas_event = None

    # --- Gas paid (native view -> USDC human amount) ---
    if to_address and not is_native_sentinel(to_address):
        usdc_gas_paid = calculate_gas_paid_usdc(
            gas_used=receipt["gasUsed"],
            effective_gas_price_wei=receipt.get("effectiveGasPrice", gas_price_fallback),
        )
        project_id = resolve_project_id(to_address, contract_project_map)
        gas_event = {
            "tx_hash": tx_hash.hex(),
            "contract_address": to_address.lower(),
            "project_id": project_id,
            "usdc_gas_paid": str(usdc_gas_paid),
            "block_number": block_number,
            "ts": block_ts,
        }

    # --- Tracked token Transfer events ---
    token_flows = []
    for log in receipt["logs"]:
        log_address = log["address"].lower()
        if log_address not in TRACKED_TOKENS:
            continue
        if not log["topics"] or log["topics"][0].hex() != TRANSFER_EVENT_TOPIC:
            continue
        if len(log["topics"]) < 3:
            continue  # malformed/non-standard Transfer log, skip defensively

        token_info = TRACKED_TOKENS[log_address]
        from_addr = "0x" + log["topics"][1].hex()[-40:]
        to_addr = "0x" + log["topics"][2].hex()[-40:]
        raw_amount = int(log["data"].hex(), 16) if log["data"] else 0
        amount = decode_erc20_transfer_amount(raw_amount, token_info["decimals"])

        token_flows.append({
            "token_address": log_address,
            "from_address": from_addr,
            "to_address": to_addr,
            "amount": str(amount),
            "usd_value": str(amount) if token_info["symbol"] in USD_PEGGED_1_TO_1 else None,
            "block_number": block_number,
            "ts": block_ts,
        })

    return gas_event, token_flows


def process_block(w3, block_number: int, contract_project_map: dict, sticky: "_StickyPoolIndex" = None):
    """
    Fetch one block, decode its transactions and logs. Sequential —
    one eth_getTransactionReceipt round-trip per transaction. Kept for
    backward compatibility and the existing test suite
    (ingestion/tests/test_worker.py); run() no longer calls this — see
    process_blocks_concurrent() below, which is the actual fix for
    docs/BUGS.md #5.

    `w3` may be a single Web3 (as in existing tests) or a list of Web3
    instances (an RPC endpoint pool) — see _as_pool(). `sticky` defaults to
    a fresh _StickyPoolIndex() when not supplied (existing single-w3 tests
    don't need to care about it).
    Returns (gas_events: list[dict], token_flows: list[dict]).
    """
    pool = _as_pool(w3)
    sticky = sticky if sticky is not None else _StickyPoolIndex()
    block = _call_on_pool(pool, sticky, "get_block", block_number, full_transactions=True)
    block_ts = datetime.fromtimestamp(block["timestamp"], tz=timezone.utc).isoformat()

    gas_events = []
    all_token_flows = []

    for tx in block["transactions"]:
        receipt = _call_on_pool(pool, sticky, "get_transaction_receipt", tx["hash"])
        gas_event, token_flows = _decode_transaction(
            tx["hash"], block_number, block_ts, tx.get("to"),
            tx.get("gasPrice", 0), receipt, contract_project_map,
        )
        if gas_event:
            gas_events.append(gas_event)
        all_token_flows.extend(token_flows)

    return gas_events, all_token_flows


# How many eth_getTransactionReceipt calls to have in flight at once (per
# endpoint attempt). This is the actual fix for docs/BUGS.md #5: measured
# directly, the worker's per-tx receipt calls were ~0.3-0.5 blocks/sec
# sequential vs Arc's real ~2 blocks/sec — because each call is a separate
# network round-trip and they were happening one at a time. web3.py's true
# JSON-RPC batch_requests() API does not exist in this project's pinned
# major version (web3>=6.15,<7 — confirmed directly against the installed
# 6.20.4, not assumed; it was added in web3.py 7.x). Rather than take on a
# major dependency bump this fix can't fully verify against the real Arc RPC
# from a sandboxed environment, this instead fires the SAME unchanged
# get_transaction_receipt() calls concurrently via a thread pool, overlapping
# their network latency instead of reducing the number of requests. Decode
# logic (_decode_transaction) is completely untouched by this change.
#
# LOWERED from 10 -> 3 on 2026-09-26 after a real 429 was observed in
# production. Endpoint rotation (see the pool comment above) is now the
# primary defense against rate-limiting; this concurrency knob is secondary
# — raise only after watching several real cron runs at 3 with zero 429s.
RPC_CONCURRENCY = int(os.environ.get("RPC_CONCURRENCY", "3"))


def fetch_receipts_concurrent(w3, tx_hashes: list, sticky: "_StickyPoolIndex" = None) -> dict:
    """
    Fetch every receipt in tx_hashes concurrently instead of one at a time.
    Returns {tx_hash: receipt}. Each individual call rotates across the
    full RPC endpoint pool starting from the shared sticky.index (see
    _call_on_pool) and retries transient 429/5xx errors within each
    endpoint (see _call_with_retry); an exception that survives every
    endpoint propagates via future.result() exactly as a failure mid-loop
    did before — run()'s existing try/except still catches it and skips
    advancing the checkpoint.

    `w3` may be a single Web3 or a list (pool) — see _as_pool().
    """
    pool = _as_pool(w3)
    sticky = sticky if sticky is not None else _StickyPoolIndex()
    receipts = {}
    with ThreadPoolExecutor(max_workers=RPC_CONCURRENCY) as executor:
        future_to_hash = {
            executor.submit(_call_on_pool, pool, sticky, "get_transaction_receipt", h): h
            for h in tx_hashes
        }
        for future in as_completed(future_to_hash):
            h = future_to_hash[future]
            receipts[h] = future.result()
    return receipts


def process_blocks_concurrent(w3, block_numbers: list, contract_project_map: dict, sticky: "_StickyPoolIndex" = None):
    """
    The actual fix for docs/BUGS.md #5 — used by run() instead of calling
    process_block() once per block. Blocks are still fetched sequentially
    (one eth_getBlockByNumber per block; this is NOT the bottleneck —
    receipts scale with tx-per-block and blocks don't, see docs/BUGS.md #5's
    own measurement). Every transaction receipt across every block in this
    run is then fetched concurrently in one pass via fetch_receipts_concurrent(),
    instead of one full block-by-block, tx-by-tx sequential pass.

    `w3` may be a single Web3 or a list (pool) — see _as_pool(). `sticky`
    (a shared _StickyPoolIndex) carries the last-known-good endpoint across
    every block-fetch and every receipt-fetch in this call, so a run spends
    at most one round of fallback attempts finding a working endpoint, not
    one round per call.
    Returns (gas_events: list[dict], token_flows: list[dict]) across all
    given blocks, same shape as calling process_block() repeatedly and
    concatenating results.
    """
    pool = _as_pool(w3)
    sticky = sticky if sticky is not None else _StickyPoolIndex()
    tx_order = []
    tx_meta = {}
    for block_number in block_numbers:
        block = _call_on_pool(pool, sticky, "get_block", block_number, full_transactions=True)
        block_ts = datetime.fromtimestamp(block["timestamp"], tz=timezone.utc).isoformat()
        for tx in block["transactions"]:
            tx_order.append(tx["hash"])
            tx_meta[tx["hash"]] = (block_number, block_ts, tx.get("to"), tx.get("gasPrice", 0))

    receipts = fetch_receipts_concurrent(pool, tx_order, sticky)

    all_gas_events = []
    all_token_flows = []
    for tx_hash in tx_order:
        block_number, block_ts, to_address, gas_price_fallback = tx_meta[tx_hash]
        receipt = receipts[tx_hash]
        gas_event, token_flows = _decode_transaction(
            tx_hash, block_number, block_ts, to_address, gas_price_fallback, receipt, contract_project_map,
        )
        if gas_event:
            all_gas_events.append(gas_event)
        all_token_flows.extend(token_flows)

    return all_gas_events, all_token_flows


def run():
    client = get_client()
    pool = get_web3_pool()
    sticky = _StickyPoolIndex()

    last_synced = get_last_synced_block(client, DEFAULT_START_BLOCK)
    latest_block = _block_number_on_pool(pool, sticky)

    if last_synced >= latest_block:
        print(f"Already synced through block {last_synced}, chain tip is {latest_block}. Nothing to do.")
        return

    end_block = min(latest_block, last_synced + MAX_BLOCKS_PER_RUN)
    contract_project_map = load_contract_project_map(client)

    print(f"Syncing blocks {last_synced + 1}..{end_block} (chain tip: {latest_block})")

    try:
        block_numbers = list(range(last_synced + 1, end_block + 1))
        all_gas_events, all_token_flows = process_blocks_concurrent(pool, block_numbers, contract_project_map, sticky)
    except Exception as exc:
        # Deliberately do NOT advance the checkpoint on failure — the next
        # run resumes from last_synced, per docs/AUDIT.md's idempotency check.
        print(f"Ingestion failed partway through: {exc}", file=sys.stderr)
        raise

    upsert_gas_events(client, all_gas_events)
    upsert_token_flows(client, all_token_flows)
    update_last_synced_block(client, end_block)

    print(f"Done. Wrote {len(all_gas_events)} gas events, {len(all_token_flows)} token flows. Checkpoint now at {end_block}.")


if __name__ == "__main__":
    from discovery import run_discovery  # imported here, not at module level,
    # to avoid a circular import — discovery.py now imports worker.py's RPC
    # pool machinery (get_web3_pool, _StickyPoolIndex, _call_on_pool) for
    # its EOA check, so worker.py can't import discovery at module level
    # anymore without both modules trying to fully load each other first.

    start = time.monotonic()
    try:
        run()
    except Exception:
        # run_discovery() is independent of ingestion succeeding — a 429
        # (or any other) failure in run() should not also silently prevent
        # discovery from processing whatever unmapped contracts already
        # exist in gas_events from prior successful runs. Re-raise after,
        # so the job still shows red in Actions (a real ingestion failure
        # should not go unnoticed), but discovery gets its chance first.
        discovery_result = run_discovery()
        print(f"Discovery: {discovery_result['touched']} touched, "
              f"{discovery_result['classified']} classified, "
              f"{discovery_result['promoted']} promoted.")
        raise
    discovery_result = run_discovery()
    print(f"Discovery: {discovery_result['touched']} touched, "
          f"{discovery_result['classified']} classified, "
          f"{discovery_result['promoted']} promoted.")
    print(f"Finished in {time.monotonic() - start:.1f}s")
