"""
Tests for tvl.py. Covers net-balance calculation, multi-contract/multi-token
aggregation, the untracked-token exclusion, and the negative-balance clamp
that keeps TVL from looking falsely precise on sparse early data
(docs/BUGS.md #3).
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tvl import calculate_contract_token_balance, calculate_project_tvl

USDC = "0x3600000000000000000000000000000000000000"
EURC = "0xbef5f6d51cb62b58e6a8f77868681825c6fe21c1"
UNTRACKED = "0x000000000000000000000000000000000dead1"
CONTRACT_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
CONTRACT_B = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
USER = "0xcccccccccccccccccccccccccccccccccccccccc"


def _flow(token, from_addr, to_addr, amount):
    return {"token_address": token, "from_address": from_addr, "to_address": to_addr, "amount": amount}


def test_calculate_contract_token_balance_net_of_in_and_out():
    flows = [
        _flow(USDC, USER, CONTRACT_A, "100"),
        _flow(USDC, CONTRACT_A, USER, "30"),
    ]
    assert calculate_contract_token_balance(flows, CONTRACT_A, USDC) == Decimal("70")


def test_calculate_contract_token_balance_case_insensitive():
    flows = [_flow(USDC.upper(), USER, CONTRACT_A.upper(), "50")]
    assert calculate_contract_token_balance(flows, CONTRACT_A, USDC) == Decimal("50")


def test_calculate_contract_token_balance_ignores_other_tokens():
    flows = [_flow(EURC, USER, CONTRACT_A, "999")]
    assert calculate_contract_token_balance(flows, CONTRACT_A, USDC) == Decimal("0")


def test_calculate_contract_token_balance_empty_flows():
    assert calculate_contract_token_balance([], CONTRACT_A, USDC) == Decimal("0")


def test_calculate_project_tvl_sums_across_contracts_and_tokens():
    flows = [
        _flow(USDC, USER, CONTRACT_A, "100"),
        _flow(EURC, USER, CONTRACT_B, "40"),
    ]
    tvl = calculate_project_tvl(flows, [CONTRACT_A, CONTRACT_B])
    assert tvl == Decimal("140")


def test_calculate_project_tvl_ignores_untracked_token():
    flows = [_flow(UNTRACKED, USER, CONTRACT_A, "1000000")]
    assert calculate_project_tvl(flows, [CONTRACT_A]) == Decimal("0")


def test_calculate_project_tvl_clamps_negative_contract_balance_to_zero():
    # Contract sent more than it received in this window (partial data) —
    # must not go negative and drag down TVL from other contracts.
    flows = [
        _flow(USDC, CONTRACT_A, USER, "500"),  # only an outflow visible
        _flow(USDC, USER, CONTRACT_B, "200"),
    ]
    tvl = calculate_project_tvl(flows, [CONTRACT_A, CONTRACT_B])
    assert tvl == Decimal("200")


def test_calculate_project_tvl_no_flows_returns_zero_not_placeholder():
    assert calculate_project_tvl([], [CONTRACT_A]) == Decimal("0")
