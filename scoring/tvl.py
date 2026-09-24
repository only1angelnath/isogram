"""
tvl.py — TVL calculation from token_flows.

Per docs/PRD.md §4 and docs/IMPLEMENTATION_PLAN.md Week 2, TVL is core, not
stretch. TVL for a project = the current on-chain balance of tracked,
USD-priced tokens (USDC, EURC, USYC — see docs/architecture_essentials.md)
held by that project's known contracts.

A contract's balance in a given token is the net of every inflow minus every
outflow recorded in token_flows for that (contract, token) pair. This is
correct as long as token_flows is a complete record since the contract first
held any of that token — true here since ingestion started at (near) mainnet
genesis for this token set. See docs/BUGS.md #3: Arc mainnet is only days old
at time of writing, so balances/TVL will be small and sparse for a while.
That's expected, not a bug — do not fabricate a fuller-looking number.

Only tokens in PRICED_TOKENS contribute to TVL. All three are USD-pegged
1:1 per docs/architecture_essentials.md, so for v1 the token amount IS the
USD value — no separate price oracle needed. (EURC is technically EUR-pegged,
not USD-pegged; treating it as ~1:1 USD is a deliberate v1 simplification,
not yet the subject of an ADR since it's a small approximation relative to
having no EUR/USD rate source at all. Revisit before EURC volume is material.)

This module never sums native-view and ERC-20-view USDC — it only ever reads
token_flows.amount, which is already the 6-decimal ERC-20 human view (see
docs/architecture_essentials.md and ingestion/decode.py).
"""

from decimal import Decimal
from typing import Iterable

# USD-priced tokens tracked on Arc for TVL purposes (all 1:1-ish USD pegged).
PRICED_TOKENS = {
    "0x3600000000000000000000000000000000000000",  # USDC
    "0xbef5f6d51cb62b58e6a8f77868681825c6fe21c1",  # EURC (v1 approximation: treated as 1:1 USD)
    "0x8a5d989bbb96929f689b0200f435f53da42bf490",  # USYC
}


def calculate_contract_token_balance(
    flows: Iterable[dict],
    contract_address: str,
    token_address: str,
) -> Decimal:
    """
    Net balance of `token_address` held by `contract_address`: sum of amounts
    received minus sum of amounts sent, over `flows`. Address comparisons are
    case-insensitive. `flows` items are expected to look like token_flows
    rows: {token_address, from_address, to_address, amount, ...}.
    """
    contract_address = contract_address.lower()
    token_address = token_address.lower()
    balance = Decimal("0")
    for flow in flows:
        if (flow.get("token_address") or "").lower() != token_address:
            continue
        amount = Decimal(str(flow["amount"]))
        to_addr = (flow.get("to_address") or "").lower()
        from_addr = (flow.get("from_address") or "").lower()
        if to_addr == contract_address:
            balance += amount
        if from_addr == contract_address:
            balance -= amount
    return balance


def calculate_project_tvl(flows: Iterable[dict], project_contracts: Iterable[str]) -> Decimal:
    """
    Sum, across every contract belonging to a project and every priced token,
    the net token balance held by that contract.

    Per-contract-per-token balances are clamped at 0 before summing: a
    negative balance only ever means the data window doesn't cover a
    contract's full history yet (see docs/BUGS.md #3), and letting a negative
    number offset a positive one elsewhere would understate TVL in a way
    that looks precise but isn't. A project with no flows yet returns
    Decimal("0"), never a fabricated placeholder.
    """
    flows = list(flows)
    total = Decimal("0")
    for contract in project_contracts:
        for token in PRICED_TOKENS:
            balance = calculate_contract_token_balance(flows, contract, token)
            if balance > 0:
                total += balance
    return total
