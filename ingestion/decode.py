"""
decode.py — USDC / native decimal conversion helpers.

THE ONE RULE THIS FILE ENFORCES (see docs/architecture_essentials.md):
Arc's native asset and the USDC ERC-20 contract
(0x3600000000000000000000000000000000000000) are the SAME underlying
balance, shown at two different decimal resolutions:
  - native view: 18 decimals — used ONLY for gas / msg.value
  - ERC-20 view: 6 decimals — used for balances, transfers, storage, display

Every amount that leaves this module is a human-readable USDC amount
(e.g. Decimal("1") for one USDC), computed from whichever raw view the data
came from. Never sum a native-view raw integer and an ERC-20-view raw
integer directly, and never treat native and ERC-20 USDC as two different
assets when aggregating — see docs/BUGS.md #1.
"""

from decimal import Decimal

NATIVE_DECIMALS = 18
USDC_DECIMALS = 6
USDC_CONTRACT_ADDRESS = "0x3600000000000000000000000000000000000000"

_NATIVE_SENTINELS = {
    "0x0000000000000000000000000000000000000000",
    "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
}


def native_wei_to_usdc(wei_amount: int) -> Decimal:
    """
    Convert a native-view amount (18 decimals, gas/msg.value only) into a
    human USDC amount (e.g. 1 USDC in native view -> Decimal("1")), the same
    convention decode_erc20_transfer_amount() uses for the ERC-20 view.
    """
    if wei_amount < 0:
        raise ValueError("wei_amount must be non-negative")
    return Decimal(wei_amount) / Decimal(10 ** NATIVE_DECIMALS)


def calculate_gas_paid_usdc(gas_used: int, effective_gas_price_wei: int) -> Decimal:
    """
    gas_used * effective_gas_price gives the total fee in native wei
    (18-decimal view). Converts that to the 6-decimal USDC view for storage
    in gas_events.usdc_gas_paid (see docs/SCHEMA.md).
    """
    if gas_used < 0 or effective_gas_price_wei < 0:
        raise ValueError("gas_used and effective_gas_price_wei must be non-negative")
    total_wei = gas_used * effective_gas_price_wei
    return native_wei_to_usdc(total_wei)


def is_native_sentinel(address: str) -> bool:
    """
    True if `address` is a native-token sentinel address, not a real ERC-20
    contract. NEVER call decimals() on one of these — it will revert
    (see docs/BUGS.md #2).
    """
    return address.lower() in _NATIVE_SENTINELS


def decode_erc20_transfer_amount(raw_amount: int, token_decimals: int) -> Decimal:
    """
    Convert a raw ERC-20 Transfer event `value` into a human Decimal using
    that token's own decimals(). For USDC / EURC / USYC on Arc this is 6,
    but this function stays generic — always pass the token's real decimals,
    never assume 6 for an unknown token.
    """
    if token_decimals < 0:
        raise ValueError("token_decimals must be non-negative")
    if raw_amount < 0:
        raise ValueError("raw_amount must be non-negative")
    return Decimal(raw_amount) / Decimal(10 ** token_decimals)
