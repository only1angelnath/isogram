"""
Tests for tvl.py's on-chain balance path (the version used since 2026-09-30).
Replaces tests that targeted the removed flow-history functions
(calculate_contract_token_balance / calculate_project_tvl), which made
`pytest` fail at collection. No network: a fake Web3 pool answers eth_call.
"""

import sys
from decimal import Decimal
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tvl
from tvl import (
    PRICED_TOKENS,
    _decode_balance,
    _encode_balance_of_calldata,
    fetch_contract_token_balance,
    fetch_project_tvl_onchain,
)

USDC = "0x3600000000000000000000000000000000000000"
EURC = "0xbef5f6d51cb62b58e6a8f77868681825c6fe21c1"
HOLDER_1 = "0x" + "11" * 20
HOLDER_2 = "0x" + "22" * 20


def _raw(units_6_dec: int) -> bytes:
    return units_6_dec.to_bytes(32, "big")


class _Eth:
    def __init__(self, balances, error=None):
        self.balances, self.error, self.calls = balances, error, []

    def call(self, tx):
        self.calls.append(tx)
        if self.error:
            raise self.error
        token = tx["to"].lower()
        holder = "0x" + tx["data"][-40:]
        return _raw(self.balances.get((token, holder.lower()), 0))


class _W3:
    def __init__(self, balances=None, error=None):
        self.eth = _Eth(balances or {}, error)


def test_encode_balance_of_calldata_pads_address_to_32_bytes():
    data = _encode_balance_of_calldata(HOLDER_1)
    assert data.startswith("0x70a08231") and len(data) == 2 + 8 + 64
    assert data.endswith("11" * 20)


def test_decode_balance_applies_6_decimals_and_handles_empty():
    assert _decode_balance(_raw(1_500_000), 6) == Decimal("1.5")
    assert _decode_balance(b"", 6) == Decimal(0)
    assert _decode_balance(None, 6) == Decimal(0)


def test_fetch_contract_token_balance_reads_the_requested_token_only():
    w3 = _W3({(USDC, HOLDER_1): 2_000_000, (EURC, HOLDER_1): 9_000_000})
    assert fetch_contract_token_balance([w3], HOLDER_1, USDC, 6) == Decimal(2)


def test_project_tvl_sums_contracts_and_priced_tokens_and_ignores_zero():
    w3 = _W3({(USDC, HOLDER_1): 10_000_000, (EURC, HOLDER_1): 1_000_000, (USDC, HOLDER_2): 5_000_000})
    assert fetch_project_tvl_onchain([w3], [HOLDER_1, HOLDER_2]) == Decimal(16)
    # every contract queried against every priced token
    assert len(w3.eth.calls) == 2 * len(PRICED_TOKENS)


def test_project_tvl_zero_balances_returns_zero_not_placeholder():
    assert fetch_project_tvl_onchain([_W3()], [HOLDER_1]) == Decimal(0)
    assert fetch_project_tvl_onchain([_W3()], []) == Decimal(0)


def _http_error(status):
    resp = requests.Response()
    resp.status_code = status
    return requests.exceptions.HTTPError(response=resp)


def test_pool_falls_through_after_429_retries(monkeypatch):
    monkeypatch.setattr(tvl.time, "sleep", lambda s: None)
    throttled = _W3(error=_http_error(429))
    good = _W3({(USDC, HOLDER_1): 3_000_000})
    assert fetch_contract_token_balance([throttled, good], HOLDER_1, USDC, 6) == Decimal(3)
    assert len(throttled.eth.calls) == tvl._RETRY_ATTEMPTS


def test_non_retryable_http_error_is_not_retried(monkeypatch):
    monkeypatch.setattr(tvl.time, "sleep", lambda s: None)
    broken = _W3(error=_http_error(400))
    with pytest.raises(requests.exceptions.HTTPError):
        fetch_contract_token_balance([broken], HOLDER_1, USDC, 6)
    assert len(broken.eth.calls) == 1
