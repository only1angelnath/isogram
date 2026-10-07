"""
rollup.py - rollup-based ingestion path (2026-10-04).

WHY THIS EXISTS: Arc produces ~12 tx/block (~2M tx/day). Storing one
gas_events row per transaction (~310 bytes) cannot fit Supabase's 0.5 GB free
tier even for one day of full coverage (DB hit 648 MB), and fetching one
receipt per transaction capped throughput at ~1.3 blocks/s against a chain
producing ~1.97/s (ingestion fell ~6 days behind - see docs/BUGS.md).

HOW IT WORKS NOW:
  * 2 RPC calls per block, not 1 + one per tx: eth_getBlockByNumber (header,
    for the timestamp) + eth_getBlockReceipts (every receipt in the block).
  * Receipts are aggregated IN MEMORY into per-day rollups (BatchAccumulator).
    No per-transaction rows are stored.
  * Each sub-batch (BATCH_BLOCKS blocks) is applied through the Postgres
    function apply_ingest_batch(), which adds the deltas AND advances
    sync_state in ONE transaction. Exactly-once: a crash can never
    double-count or skip a batch, and overlapping cron runs are rejected by
    the function's checkpoint check instead of corrupting totals.

THE ONE CORRECTNESS RULE (docs/architecture_essentials.md): gas is computed
only via decode.calculate_gas_paid_usdc() (native 18-decimal wei -> 6-decimal
USDC view) and token amounts only via decode.decode_erc20_transfer_amount().
Native and ERC-20 USDC are the same pool of funds; nothing here ever sums the
two views.
"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import ROUND_HALF_EVEN, Decimal

import requests

from decode import (
    calculate_gas_paid_usdc,
    decode_erc20_transfer_amount,
    is_native_sentinel,
)
from worker import (
    RPC_CONCURRENCY,
    TRACKED_TOKENS,
    TRANSFER_EVENT_TOPIC,
    _call_with_retry,
    _StickyPoolIndex,
)

# --- USDC has TWO event streams (docs.arc.io/arc/references/usdc-system-events) ---
# * 0xffff...fffe  native system log (EIP-7708), 18 decimals: logged ONCE for
#   EVERY explicit USDC movement - native sends, ERC-20 transfers, mint, burn.
# * 0x3600...0000  ERC-20 contract, 6 decimals: ERC-20-interface calls ONLY.
# An ERC-20 transfer() emits BOTH, so counting both double-counts, and the
# ERC-20 stream alone MISSES plain native sends (measured 2026-10-05 on 200
# live blocks: it missed 74.4% of USDC volume). The system log is therefore the
# single source for USDC; the 0x3600 log is deliberately IGNORED here. The
# 18-decimal value is converted to the 6-decimal view exactly once, below, and
# rows are keyed by the canonical USDC address 0x3600... (the token's identity).
SYSTEM_USDC_EMITTER = "0xfffffffffffffffffffffffffffffffffffffffe"
USDC_ERC20_ADDRESS = "0x3600000000000000000000000000000000000000"
SYSTEM_LOG_DECIMALS = 18
_ZERO_TOPIC = "0x" + "0" * 64
_USDC_QUANTUM = Decimal("0.000001")  # stored/displayed USDC is always the 6-decimal view

# Blocks per atomic apply. Smaller = less work lost on a failure and smaller
# request bodies; larger = fewer DB round-trips.
BATCH_BLOCKS = int(os.environ.get("BATCH_BLOCKS", "500"))

# Stop starting new sub-batches after this many seconds (always completes at
# least one). Checkpoint is saved per sub-batch, so stopping here loses nothing.
RUN_TIME_BUDGET_SECONDS = float(os.environ.get("RUN_TIME_BUDGET_SECONDS", "1500"))

# Follow-the-tip mode (2026-10-07). GitHub's scheduled trigger is best effort: a `*/5`
# cron was observed firing only every 3-5 HOURS, so a run that exits once it reaches
# the tip leaves the data hours stale (measured: lag grew 21h -> 32h). With this on, a
# run that catches up keeps polling for new blocks until RUN_TIME_BUDGET_SECONDS ends,
# so data stays seconds-fresh for the whole job and the next job simply continues.
FOLLOW_TIP = os.environ.get("FOLLOW_TIP", "true").strip().lower() in ("1", "true", "yes")
TIP_POLL_SECONDS = float(os.environ.get("TIP_POLL_SECONDS", "10"))


class RpcResultError(Exception):
    """An endpoint answered, but with a JSON-RPC error or a null result."""


def _hex_to_int(value) -> int:
    if isinstance(value, int):
        return value
    return int(value, 16)


def _raw_rpc_on_pool(pool: list, sticky: "_StickyPoolIndex", method: str, params: list):
    """
    Raw JSON-RPC call with the same endpoint-rotation + 429/5xx retry
    behaviour as worker._call_on_pool, but via provider.make_request so it
    can call methods web3.py 6.x has no wrapper for (eth_getBlockReceipts).
    An endpoint that errors, times out, or returns a null result (e.g. it
    does not support the method) is skipped in favour of the next one.
    """
    n = len(pool)
    start = sticky.index % n
    last_exc = None
    for offset in range(n):
        i = (start + offset) % n
        w3 = pool[i]
        try:
            resp = _call_with_retry(w3.provider.make_request, method, params)
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            continue
        if not isinstance(resp, dict) or resp.get("error") is not None or resp.get("result") is None:
            err = resp.get("error") if isinstance(resp, dict) else resp
            last_exc = RpcResultError(f"{method} on endpoint #{i} gave no result: {err!r}")
            continue
        sticky.index = i
        return resp["result"]
    raise last_exc


def fetch_block(pool: list, sticky: "_StickyPoolIndex", block_number: int):
    """Returns (block_number, block_timestamp_int, receipts: list[dict])."""
    header = _raw_rpc_on_pool(pool, sticky, "eth_getBlockByNumber", [hex(block_number), False])
    receipts = _raw_rpc_on_pool(pool, sticky, "eth_getBlockReceipts", [hex(block_number)])
    return block_number, _hex_to_int(header["timestamp"]), receipts


class BatchAccumulator:
    """
    Pure in-memory aggregation of blocks into the rollup payload expected by
    the apply_ingest_batch() SQL function. No network, no DB - unit-testable.
    Order-independent (sums and sets), so blocks may be added as they finish.
    """

    def __init__(self, tracked_contracts: set):
        self.tracked = {c.lower() for c in tracked_contracts}
        self.contracts = {}       # (day, to) -> [tx, failed, Decimal gas]
        self.network = {}         # day -> dict of totals
        self.tokens = {}          # (day, token) -> [count, Decimal volume]
        self.addresses = {}       # day -> set of 40-hex sender addresses
        self.contract_users = {}  # day -> {tracked contract -> set of senders}
        self.missing_from = 0
        self.max_block_ts = 0     # newest block timestamp seen (freshness)

    def _net(self, day: str) -> dict:
        return self.network.setdefault(day, {
            "tx_count": 0, "failed_tx_count": 0, "usdc_gas_paid": Decimal("0"),
            "contract_creations": 0, "blocks": 0, "token_transfer_count": 0,
        })

    def add_block(self, block_timestamp: int, receipts: list) -> None:
        self.max_block_ts = max(self.max_block_ts, block_timestamp)
        day = datetime.fromtimestamp(block_timestamp, tz=timezone.utc).date().isoformat()
        net = self._net(day)
        net["blocks"] += 1

        for r in receipts:
            status = r.get("status")
            failed = status is not None and _hex_to_int(status) == 0
            # No effectiveGasPrice -> we cannot compute gas honestly; fail loud
            # (the run aborts, checkpoint stays put) rather than record a guess.
            gas_usdc = calculate_gas_paid_usdc(
                gas_used=_hex_to_int(r["gasUsed"]),
                effective_gas_price_wei=_hex_to_int(r["effectiveGasPrice"]),
            )
            to_address = r.get("to")
            to_l = to_address.lower() if to_address else None

            net["tx_count"] += 1
            net["usdc_gas_paid"] += gas_usdc
            if failed:
                net["failed_tx_count"] += 1
            if to_l is None:
                net["contract_creations"] += 1

            if to_l and not is_native_sentinel(to_l):
                entry = self.contracts.setdefault((day, to_l), [0, 0, Decimal("0")])
                entry[0] += 1
                entry[1] += 1 if failed else 0
                entry[2] += gas_usdc

            sender = (r.get("from") or "").lower()
            if sender.startswith("0x") and len(sender) == 42:
                sender_hex = sender[2:]
                self.addresses.setdefault(day, set()).add(sender_hex)
                if to_l in self.tracked:
                    self.contract_users.setdefault(day, {}).setdefault(to_l, set()).add(sender_hex)
            else:
                self.missing_from += 1

            for log in r.get("logs") or []:
                emitter = (log.get("address") or "").lower()
                if emitter == USDC_ERC20_ADDRESS:
                    continue  # duplicate of the system log (see SYSTEM_USDC_EMITTER note)
                topics = log.get("topics") or []
                if len(topics) < 3 or topics[0].lower() != TRANSFER_EVENT_TOPIC:
                    continue
                data = log.get("data") or "0x"
                raw_amount = int(data, 16) if data not in ("0x", "") else 0

                if emitter == SYSTEM_USDC_EMITTER:
                    # Mint/burn are supply changes (zero-address leg), not movement
                    # between holders: excluded from transfer count and volume.
                    if topics[1].lower() == _ZERO_TOPIC or topics[2].lower() == _ZERO_TOPIC:
                        continue
                    token = USDC_ERC20_ADDRESS
                    amount = decode_erc20_transfer_amount(raw_amount, SYSTEM_LOG_DECIMALS)
                else:
                    info = TRACKED_TOKENS.get(emitter)
                    if info is None:
                        continue
                    token = emitter
                    amount = decode_erc20_transfer_amount(raw_amount, info["decimals"])

                tok = self.tokens.setdefault((day, token), [0, Decimal("0")])
                tok[0] += 1
                tok[1] += amount
                net["token_transfer_count"] += 1

    def to_payload(self) -> dict:
        """JSON-serialisable kwargs for apply_ingest_batch (Decimals as strings)."""
        return {
            "p_contracts": [
                {"day": d, "contract_address": c, "tx_count": v[0],
                 "failed_tx_count": v[1], "usdc_gas_paid": str(v[2])}
                for (d, c), v in self.contracts.items()
            ],
            "p_network": [
                {"day": d, **{k: (str(x) if isinstance(x, Decimal) else x) for k, x in v.items()}}
                for d, v in self.network.items()
            ],
            "p_tokens": [
                {"day": d, "token_address": t, "transfer_count": v[0],
                 "volume": str(v[1].quantize(_USDC_QUANTUM, rounding=ROUND_HALF_EVEN))}
                for (d, t), v in self.tokens.items()
            ],
            "p_addresses": {d: sorted(s) for d, s in self.addresses.items()},
            "p_contract_users": {
                d: {c: sorted(s) for c, s in per.items()}
                for d, per in self.contract_users.items()
            },
        }


def process_batch(pool: list, sticky: "_StickyPoolIndex", block_numbers: list, tracked: set,
                  concurrency: int = None) -> BatchAccumulator:
    """Fetch blocks concurrently and aggregate them. Any failure aborts the whole batch."""
    acc = BatchAccumulator(tracked)
    workers = concurrency or RPC_CONCURRENCY
    ex = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = [ex.submit(fetch_block, pool, sticky, n) for n in block_numbers]
        for fut in as_completed(futures):
            _, ts, receipts = fut.result()
            acc.add_block(ts, receipts)
    except BaseException:
        ex.shutdown(wait=False, cancel_futures=True)
        raise
    ex.shutdown(wait=True)
    return acc


def apply_batch(client, start_block: int, end_block: int, acc: BatchAccumulator) -> None:
    """Atomically apply the batch AND advance sync_state (see the SQL function)."""
    params = {"p_start_block": start_block, "p_end_block": end_block, **acc.to_payload()}
    if acc.max_block_ts:
        # Recorded in sync_state atomically with the checkpoint -> pipeline_status().data_through
        params["p_end_block_ts"] = datetime.fromtimestamp(acc.max_block_ts, tz=timezone.utc).isoformat()
    client.rpc("apply_ingest_batch", params).execute()


def run_rollup(client, pool: list, sticky: "_StickyPoolIndex", contract_project_map: dict,
               last_synced: int, latest_block: int, max_blocks: int, tip_fn=None) -> dict:
    """
    Process blocks after `last_synced` in atomic sub-batches, never more than
    `max_blocks` blocks in total this run.

    Once it reaches the chain tip: with FOLLOW_TIP and a `tip_fn` (callable returning
    the current chain tip) it keeps polling every TIP_POLL_SECONDS and applying new
    blocks until RUN_TIME_BUDGET_SECONDS is used up; otherwise it stops. The
    checkpoint is advanced per sub-batch, so stopping at any point loses nothing.
    """
    t0 = time.monotonic()
    cap = last_synced + max_blocks
    end_block = min(latest_block, cap)
    tracked = set(contract_project_map)
    cursor = last_synced + 1
    blocks_done = 0
    batches = 0
    while True:
        over_budget = time.monotonic() - t0 > RUN_TIME_BUDGET_SECONDS

        if cursor > end_block:
            # Caught up with what we knew about. Follow the tip, or finish.
            if over_budget or not FOLLOW_TIP or tip_fn is None or cursor > cap:
                break
            time.sleep(TIP_POLL_SECONDS)
            try:
                latest_block = tip_fn()
            except Exception as exc:  # transient RPC trouble: retry on the next poll
                print(f"tip poll failed (will retry): {exc}", file=sys.stderr)
                continue
            end_block = min(latest_block, cap)
            continue

        if over_budget and batches > 0:
            print(f"Time budget ({RUN_TIME_BUDGET_SECONDS:.0f}s) reached; stopping cleanly at {cursor - 1}.")
            break

        batch_end = min(cursor + BATCH_BLOCKS - 1, end_block)
        acc = process_batch(pool, sticky, list(range(cursor, batch_end + 1)), tracked)
        if acc.missing_from:
            print(f"WARNING: {acc.missing_from} receipts had no usable 'from' in blocks {cursor}..{batch_end}",
                  file=sys.stderr)
        apply_batch(client, cursor, batch_end, acc)
        blocks_done += batch_end - cursor + 1
        batches += 1
        elapsed = max(time.monotonic() - t0, 1e-9)
        print(f"Applied blocks {cursor}..{batch_end} ({blocks_done} total, "
              f"{blocks_done / elapsed:.1f} blocks/s, lag {latest_block - batch_end}).")
        cursor = batch_end + 1
    return {"blocks": blocks_done, "batches": batches, "checkpoint": cursor - 1,
            "lag": latest_block - (cursor - 1), "seconds": time.monotonic() - t0}


def run_maintenance(client) -> None:
    """Bound the two address tables and the contract long tail. Best-effort."""
    for fn, params in (
        # default window (8 days): unique-user counts need 7 days of distinct
        # addresses; daily counts are persisted before anything is pruned.
        ("prune_rollup_addresses", {}),
        ("prune_rollup_long_tail", {}),
    ):
        try:
            res = client.rpc(fn, params).execute()
            print(f"maintenance {fn}: {res.data}")
        except Exception as exc:  # never fail ingestion over housekeeping
            print(f"maintenance {fn} failed (non-fatal): {exc}", file=sys.stderr)
