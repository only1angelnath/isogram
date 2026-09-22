"""
Tests for decode.py. Per docs/TESTING.md, this is the highest-priority test
file in the project — decimal-conversion correctness is the #1 documented
risk in docs/BUGS.md. These tests are written before the rest of the
ingestion worker, not after.
"""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

# Allow running with `python -m pytest tests/` from the ingestion/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decode import (
    calculate_gas_paid_usdc,
    decode_erc20_transfer_amount,
    is_native_sentinel,
    native_wei_to_usdc,
)


def test_native_wei_to_usdc_one_usdc():
    # 1 USDC in native 18-decimal view = 10**18 wei
    assert native_wei_to_usdc(10**18) == Decimal("1")


def test_native_wei_to_usdc_fractional():
    assert native_wei_to_usdc(5 * 10**17) == Decimal("0.5")


def test_native_wei_to_usdc_zero():
    assert native_wei_to_usdc(0) == Decimal("0")


def test_native_wei_to_usdc_rejects_negative():
    with pytest.raises(ValueError):
        native_wei_to_usdc(-1)


def test_calculate_gas_paid_usdc_matches_hand_calculation():
    # Worked out by hand: gas_used=21000, effective_gas_price=1_000_000_000 wei (1 gwei)
    # total_wei = 21000 * 1_000_000_000 = 21_000_000_000_000
    # expected USDC = 21_000_000_000_000 / 10**18 = 0.000021
    result = calculate_gas_paid_usdc(21000, 1_000_000_000)
    assert result == Decimal("0.000021")


def test_calculate_gas_paid_usdc_rejects_negative_inputs():
    with pytest.raises(ValueError):
        calculate_gas_paid_usdc(-1, 1)
    with pytest.raises(ValueError):
        calculate_gas_paid_usdc(1, -1)


def test_is_native_sentinel_zero_address():
    assert is_native_sentinel("0x0000000000000000000000000000000000000000")


def test_is_native_sentinel_eeee_address_case_insensitive():
    assert is_native_sentinel("0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE")


def test_is_native_sentinel_false_for_usdc_contract():
    assert not is_native_sentinel("0x3600000000000000000000000000000000000000")


def test_decode_erc20_transfer_amount_usdc_six_decimals():
    # 1,000,000 raw units at 6 decimals = 1.0 USDC
    assert decode_erc20_transfer_amount(1_000_000, 6) == Decimal("1")


def test_decode_erc20_transfer_amount_rejects_negative_decimals():
    with pytest.raises(ValueError):
        decode_erc20_transfer_amount(100, -1)


def test_decode_erc20_transfer_amount_rejects_negative_amount():
    with pytest.raises(ValueError):
        decode_erc20_transfer_amount(-100, 6)


def test_native_and_erc20_views_never_double_count():
    """
    Regression test for docs/BUGS.md #1: native and ERC-20 USDC views must
    never be treated as two separate assets. Both paths below represent the
    SAME 1 USDC — summing them would silently double-count it.
    """
    native_view_amount = native_wei_to_usdc(10**18)
    erc20_view_amount = decode_erc20_transfer_amount(1_000_000, 6)
    assert native_view_amount == erc20_view_amount == Decimal("1")
