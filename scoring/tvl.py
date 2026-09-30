"""
tvl.py — TVL calculation for tracked projects.

REWRITTEN 2026-09-27 (see docs/BUGS.md): the original approach derived a
project's token balance by summing every historical token_flows row for
that (contract, token) pair. That's only correct if token_flows is a
complete, unbroken record since the contract first held any of that token
— which stopped being true the moment token_flows was truncated to recover
from a Supabase free-tier storage overrun. Any balance built up from a
transfer that happened before the truncation would be invisible and stay
wrong forever unless a fresh transfer happened to refresh it. Worse: the
retention pruning needed to keep storage under the free-tier cap going
forward would re-break this exact calculation every time it ran.

Fix: query each project contract's ACTUAL current balance directly
on-chain via eth_call (ERC-20 balanceOf), instead of replaying flow
history. TVL no longer depends on token_flows existing at all, which is
what makes retention pruning finally safe to add.

This module has its OWN small, self-contained RPC pool — deliberately not
importing ingestion/worker.py's. scoring/ is a separate deployable unit
with its own requirements.txt (docs/SCAFFOLD.md); reaching into ingestion/
would break that separation and force scoring-cron.yml to carry every RPC
secret ingestion needs, for a job that makes a tiny fraction as many calls
(a handful of projects x a few contracts x 3 tokens, once per scoring run,
vs. thousands of receipt fetches per ingestion run). A simple pool + retry
is enough at this call volume; no sticky-endpoint tracking needed.

Per docs/PRD.md §4 and docs/IMPLEMENTATION_PLAN.md Week 2, TVL is core, not
stretch. TVL for a project = the sum, across its known contracts, of each
contract's current balance of tracked, USD-priced tokens (USDC, EURC, USYC
— see docs/architecture_essentials.md).

Only tokens in PRICED_TOKENS contribute to TVL. All three are USD-pegged
1:1 per docs/architecture_essentials.md, so for v1 the token amount IS the
USD value — no separate price oracle needed. (EURC is technically EUR-pegged,
not USD-pegged; treating it as ~1:1 USD is a deliberate v1 simplification —
revisit before EURC volume is material.)
"""

import os
import sys
import time
from decimal import Decimal
from typing import Iterable

import requests
from web3 import Web3

# USD-priced tokens tracked on Arc for TVL purposes (all 1:1-ish USD pegged),
# each with its decimals — balanceOf returns a raw integer, not a pre-scaled
# amount.
PRICED_TOKENS = {
    "0x3600000000000000000000000000000000000000": 6,  # USDC
    "0xbef5f6d51cb62b58e6a8f77868681825c6fe21c1": 6,  # EURC (v1 approximation: treated as 1:1 USD)
    "0x8a5d989bbb96929f689b0200f435f53da42bf490": 6,  # USYC
}

# ERC-20 balanceOf(address) function selector: keccak256("balanceOf(address)")[:4]
_BALANCE_OF_SELECTOR = "0x70a08231"

# --- Small, self-contained RPC pool (see module docstring for why this
# isn't shared with ingestion/worker.py's) -----------------------------------

_ARC_MAINNET_RPC = os.environ.get("ARC_RPC_URL", "https://rpc.mainnet.arc.io")
_FALLBACK_URLS = [
    u.strip() for u in os.environ.get(
        "ARC_RPC_FALLBACK_URLS",
        "https://rpc.drpc.mainnet.arc.io,https://rpc.blockdaemon.mainnet.arc.io,https://rpc.quicknode.mainnet.arc.io",
    ).split(",") if u.strip()
]
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.5
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def get_web3_pool() -> list:
    """
    Build a small pool: the same dedicated endpoints ingestion uses IF the
    same env vars happen to be set for this job (cheap to reuse, no harm if
    absent), then ARC_RPC_URL and the free mirrors as fallback. Skips any
    endpoint that fails a basic connectivity check.
    """
    urls = []
    for var in ("ALCHEMY_ARC_RPC_URL", "DRPC_ARC_RPC_URL", "QUICKNODE_ARC_RPC_URL"):
        val = os.environ.get(var)
        if val:
            urls.append(val)
    urls.append(_ARC_MAINNET_RPC)
    urls += [u for u in _FALLBACK_URLS if u != _ARC_MAINNET_RPC]

    pool = []
    for url in urls:
        try:
            w3 = Web3(Web3.HTTPProvider(url))
            if w3.is_connected():
                pool.append(w3)
        except Exception as exc:
            print(f"tvl.py: RPC endpoint failed connectivity check, skipping: {url} ({exc})", file=sys.stderr)
    if not pool:
        raise RuntimeError("tvl.py: no Arc RPC endpoints reachable for TVL balance checks")
    return pool


def _call_with_retry(fn, *args, **kwargs):
    last_exc = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            return fn(*args, **kwargs)
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status not in _RETRYABLE_STATUS:
                raise
            last_exc = exc
            if attempt == _RETRY_ATTEMPTS - 1:
                break
            time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))
    raise last_exc


def _call_on_pool(pool: list, *args, **kwargs):
    """Try eth_call against each endpoint in the pool in order."""
    last_exc = None
    for w3 in pool:
        try:
            return _call_with_retry(w3.eth.call, *args, **kwargs)
        except requests.exceptions.HTTPError as exc:
            last_exc = exc
            continue
    raise last_exc


# --- Balance encoding/decoding ----------------------------------------------

def _encode_balance_of_calldata(holder_address: str) -> str:
    address_no_prefix = holder_address.lower().replace("0x", "")
    padded = address_no_prefix.rjust(64, "0")
    return _BALANCE_OF_SELECTOR + padded


def _decode_balance(raw_result, decimals: int) -> Decimal:
    if not raw_result:
        return Decimal("0")
    raw_int = int.from_bytes(raw_result, byteorder="big")
    return Decimal(raw_int) / (Decimal(10) ** decimals)


def fetch_contract_token_balance(pool: list, contract_address: str, token_address: str, decimals: int) -> Decimal:
    """Query the actual current on-chain balance of token_address held by contract_address."""
    calldata = _encode_balance_of_calldata(contract_address)
    # web3.py's eth_call validates the "to" field as a checksummed address
    # (EIP-55) and raises InvalidAddress otherwise — confirmed live
    # 2026-09-30. The holder address inside calldata doesn't need this (it's
    # raw hex data, not validated by web3.py), only the top-level "to".
    checksummed_token_address = Web3.to_checksum_address(token_address)
    raw_result = _call_on_pool(pool, {"to": checksummed_token_address, "data": calldata})
    return _decode_balance(raw_result, decimals)


def fetch_project_tvl_onchain(pool: list, project_contracts: Iterable[str]) -> Decimal:
    """
    Sum, across every contract belonging to a project and every priced
    token, that contract's CURRENT on-chain balance. A project with
    genuinely zero balances returns Decimal("0"), never a fabricated
    placeholder.
    """
    total = Decimal("0")
    for contract in project_contracts:
        for token_address, decimals in PRICED_TOKENS.items():
            balance = fetch_contract_token_balance(pool, contract, token_address, decimals)
            if balance > 0:
                total += balance
    return total
