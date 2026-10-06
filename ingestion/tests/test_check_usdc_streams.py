"""check_usdc_streams.summarize_usdc_streams: both emitters, never added together."""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_usdc_streams import (
    ERC20_USDC, SYSTEM_EMITTER, TRANSFER_TOPIC, ZERO_TOPIC, summarize_usdc_streams,
)

A = "0x" + "0" * 24 + "aa" * 20
B = "0x" + "0" * 24 + "bb" * 20


def log(addr, raw, frm=A, to=B):
    return {"address": addr, "topics": [TRANSFER_TOPIC, frm, to], "data": hex(raw)}


def test_erc20_transfer_emits_both_streams_and_is_not_native_only():
    # 2.5 USDC via the ERC-20 interface: 6-dec log (2_500_000) + 18-dec system log (2.5e18)
    rcpt = {"logs": [log(SYSTEM_EMITTER, 25 * 10**17), log(ERC20_USDC, 2_500_000)]}
    s = summarize_usdc_streams([[rcpt]])
    assert s["erc20_volume_usdc"] == Decimal("2.5") and s["system_volume_usdc"] == Decimal("2.5")
    assert s["native_only_txs"] == 0  # same movement, one real transfer - never 5.0 total


def test_plain_native_send_only_in_system_stream():
    rcpt = {"logs": [log(SYSTEM_EMITTER, 10**18)]}  # 1 USDC native send
    s = summarize_usdc_streams([[rcpt]])
    assert s["erc20_logs"] == 0 and s["system_logs"] == 1
    assert s["native_only_txs"] == 1 and s["native_only_volume_usdc"] == Decimal(1)


def test_mint_burn_and_irrelevant_logs():
    mint = {"logs": [log(SYSTEM_EMITTER, 10**18, frm=ZERO_TOPIC)]}
    burn = {"logs": [log(SYSTEM_EMITTER, 10**18, to=ZERO_TOPIC)]}
    other = {"logs": [log("0x" + "ee" * 20, 5), {"address": ERC20_USDC, "topics": ["0x01"], "data": "0x"}]}
    s = summarize_usdc_streams([[mint, burn], [other, {"logs": []}]])
    assert s["system_mints"] == 1 and s["system_burns"] == 1
    assert s["erc20_logs"] == 0 and s["txs"] == 4
