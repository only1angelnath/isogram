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
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

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
# invocation short and bounds how much work is lost if a run fails partway.
# 100 is conservative: measured processing speed (~0.3-0.5 blocks/sec,
# sequential per-tx receipt calls) is well below Arc's real ~2 blocks/sec,
# so the worker currently cannot keep pace with the chain in real time.
# See docs/BUGS.md for the tracked fix (batch RPC receipt calls).
MAX_BLOCKS_PER_RUN = int(os.environ.get("MAX_BLOCKS_PER_RUN", "100"))

# usd_value is only populated for tokens we can currently price at 1:1 USD.
# EURC is EUR-pegged, not USD-pegged — pricing it at 1:1 USD here would be
# wrong in a way that's easy to miss downstream (scoring/tvl.py makes the
# same simplification deliberately and documents it; this dict does not,
# because a wrong per-transfer usd_value is worse than a missing one).
# USYC is USD-denominated but not necessarily exactly 1:1 in practice; treated
# as 1:1 for v1 alongside USDC, consistent with scoring/tvl.py's PRICED_TOKENS.
USD_PEGGED_1_TO_1 = {"USDC", "USYC"}


def get_web3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(ARC_MAINNET_RPC))
    if not w3.is_connected():
        raise RuntimeError(f"Could not connect to Arc mainnet RPC at {ARC_MAINNET_RPC}")
    return w3


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


def process_block(w3: Web3, block_number: int, contract_project_map: dict):
    """
    Fetch one block, decode its transactions and logs. Sequential —
    one eth_getTransactionReceipt round-trip per transaction. Kept for
    backward compatibility and the existing test suite
    (ingestion/tests/test_worker.py); run() no longer calls this — see
    process_blocks_concurrent() below, which is the actual fix for
    docs/BUGS.md #5.
    Returns (gas_events: list[dict], token_flows: list[dict]).
    """
    block = w3.eth.get_block(block_number, full_transactions=True)
    block_ts = datetime.fromtimestamp(block["timestamp"], tz=timezone.utc).isoformat()

    gas_events = []
    all_token_flows = []

    for tx in block["transactions"]:
        receipt = w3.eth.get_transaction_receipt(tx["hash"])
        gas_event, token_flows = _decode_transaction(
            tx["hash"], block_number, block_ts, tx.get("to"),
            tx.get("gasPrice", 0), receipt, contract_project_map,
        )
        if gas_event:
            gas_events.append(gas_event)
        all_token_flows.extend(token_flows)

    return gas_events, all_token_flows


# How many eth_getTransactionReceipt calls to have in flight at once. This
# is the actual fix for docs/BUGS.md #5: measured directly, the worker's
# per-tx receipt calls were ~0.3-0.5 blocks/sec sequential vs Arc's real
# ~2 blocks/sec — because each call is a separate network round-trip and
# they were happening one at a time. web3.py's true JSON-RPC batch_requests()
# API does not exist in this project's pinned major version (web3>=6.15,<7 —
# confirmed directly against the installed 6.20.4, not assumed; it was added
# in web3.py 7.x). Rather than take on a major dependency bump this fix
# can't fully verify against the real Arc RPC from a sandboxed environment,
# this instead fires the SAME unchanged get_transaction_receipt() calls
# concurrently via a thread pool, overlapping their network latency instead
# of reducing the number of requests. Decode logic (_decode_transaction) is
# completely untouched by this change.
#
# Starts conservative because rpc.mainnet.arc.io's rate limit is unconfirmed
# (docs/BUGS.md #4) — raise gradually and watch for 429s/timeouts in the
# ingestion-cron workflow logs rather than maximizing this blindly.
RPC_CONCURRENCY = int(os.environ.get("RPC_CONCURRENCY", "10"))


def fetch_receipts_concurrent(w3: Web3, tx_hashes: list) -> dict:
    """
    Fetch every receipt in tx_hashes concurrently instead of one at a time.
    Returns {tx_hash: receipt}. An exception from any single call propagates
    (via future.result()) exactly as a failure mid-loop did before — run()'s
    existing try/except still catches it and skips advancing the checkpoint.
    """
    receipts = {}
    with ThreadPoolExecutor(max_workers=RPC_CONCURRENCY) as executor:
        future_to_hash = {
            executor.submit(w3.eth.get_transaction_receipt, h): h
            for h in tx_hashes
        }
        for future in as_completed(future_to_hash):
            h = future_to_hash[future]
            receipts[h] = future.result()
    return receipts


def process_blocks_concurrent(w3: Web3, block_numbers: list, contract_project_map: dict):
    """
    The actual fix for docs/BUGS.md #5 — used by run() instead of calling
    process_block() once per block. Blocks are still fetched sequentially
    (one eth_getBlockByNumber per block; this is NOT the bottleneck —
    receipts scale with tx-per-block and blocks don't, see docs/BUGS.md #5's
    own measurement). Every transaction receipt across every block in this
    run is then fetched concurrently in one pass via fetch_receipts_concurrent(),
    instead of one full block-by-block, tx-by-tx sequential pass.
    Returns (gas_events: list[dict], token_flows: list[dict]) across all
    given blocks, same shape as calling process_block() repeatedly and
    concatenating results.
    """
    tx_order = []
    tx_meta = {}
    for block_number in block_numbers:
        block = w3.eth.get_block(block_number, full_transactions=True)
        block_ts = datetime.fromtimestamp(block["timestamp"], tz=timezone.utc).isoformat()
        for tx in block["transactions"]:
            tx_order.append(tx["hash"])
            tx_meta[tx["hash"]] = (block_number, block_ts, tx.get("to"), tx.get("gasPrice", 0))

    receipts = fetch_receipts_concurrent(w3, tx_order)

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
    w3 = get_web3()

    last_synced = get_last_synced_block(client, DEFAULT_START_BLOCK)
    latest_block = w3.eth.block_number

    if last_synced >= latest_block:
        print(f"Already synced through block {last_synced}, chain tip is {latest_block}. Nothing to do.")
        return

    end_block = min(latest_block, last_synced + MAX_BLOCKS_PER_RUN)
    contract_project_map = load_contract_project_map(client)

    print(f"Syncing blocks {last_synced + 1}..{end_block} (chain tip: {latest_block})")

    try:
        block_numbers = list(range(last_synced + 1, end_block + 1))
        all_gas_events, all_token_flows = process_blocks_concurrent(w3, block_numbers, contract_project_map)
    except Exception as exc:
        # Deliberately do NOT advance the checkpoint on failure — the next
        # run resumes from last_synced, per docs/AUDIT.md's idempotency check.
        print(f"Ingestion failed partway through: {exc}", file=sys.stderr)
        raise

    upsert_gas_events(client, all_gas_events)
    upsert_token_flows(client, all_token_flows)
    update_last_synced_block(client, end_block)

    print(f"Done. Wrote {len(all_gas_events)} gas events, {len(all_token_flows)} token flows. Checkpoint now at {end_block}.")


from discovery import run_discovery

if __name__ == "__main__":
    start = time.monotonic()
    run()
    run_discovery()
    print(f"Finished in {time.monotonic() - start:.1f}s")
