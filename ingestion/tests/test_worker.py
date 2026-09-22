"""
Tests for worker.py's process_block(). Uses fabricated block/receipt/log
data (no live RPC call) to verify the wiring between raw web3 data and
decode.py is correct — this is where a subtle bug (wrong topic slicing,
wrong data parsing) would show up even though decode.py's own tests pass.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from worker import TRANSFER_EVENT_TOPIC, process_block


class FakeHex:
    """Minimal stand-in for HexBytes — needs .hex() plus hashing/equality
    so it can be used as a dict key, same as real HexBytes objects are."""

    def __init__(self, value: str):
        self._value = value

    def hex(self) -> str:
        return self._value

    def __hash__(self):
        return hash(self._value)

    def __eq__(self, other):
        if isinstance(other, FakeHex):
            return self._value == other._value
        return self._value == other


class FakeW3Eth:
    def __init__(self, block, receipts_by_hash):
        self._block = block
        self._receipts_by_hash = receipts_by_hash

    def get_block(self, block_number, full_transactions=True):
        return self._block

    def get_transaction_receipt(self, tx_hash):
        return self._receipts_by_hash[tx_hash]


class FakeW3:
    def __init__(self, block, receipts_by_hash):
        self.eth = FakeW3Eth(block, receipts_by_hash)


USDC_ADDRESS = "0x3600000000000000000000000000000000000000"


def _make_transfer_log(from_addr_hex40: str, to_addr_hex40: str, raw_amount: int):
    # Topics are 32 bytes; an address occupies the low 20 bytes (40 hex chars),
    # left-padded with zeros in the high 12 bytes (24 hex chars).
    assert len(from_addr_hex40) == 40, "test fixture bug: address must be exactly 40 hex chars"
    assert len(to_addr_hex40) == 40, "test fixture bug: address must be exactly 40 hex chars"
    topic_from = "0x" + "0" * 24 + from_addr_hex40
    topic_to = "0x" + "0" * 24 + to_addr_hex40
    return {
        "address": USDC_ADDRESS,
        "topics": [FakeHex(TRANSFER_EVENT_TOPIC), FakeHex(topic_from), FakeHex(topic_to)],
        "data": FakeHex(hex(raw_amount)),
    }


FROM_ADDR = "1" * 39 + "a"  # 40 hex chars
TO_ADDR = "2" * 39 + "b"    # 40 hex chars


def test_process_block_decodes_gas_and_transfer():
    tx_hash = "0xabc123"
    contract_address = "0x1234567890123456789012345678901234567890"

    block = {
        "timestamp": 1_726_000_000,
        "transactions": [
            {"hash": FakeHex(tx_hash), "to": contract_address, "gasPrice": 1_000_000_000}
        ],
    }
    receipt = {
        "gasUsed": 21000,
        "effectiveGasPrice": 1_000_000_000,
        "logs": [
            _make_transfer_log(
                from_addr_hex40=FROM_ADDR,
                to_addr_hex40=TO_ADDR,
                raw_amount=5_000_000,  # 5 USDC at 6 decimals
            )
        ],
    }
    w3 = FakeW3(block, {tx_hash: receipt})

    contract_project_map = {contract_address.lower(): "my-project"}

    gas_events, token_flows = process_block(w3, block_number=100, contract_project_map=contract_project_map)

    assert len(gas_events) == 1
    ge = gas_events[0]
    assert ge["tx_hash"] == tx_hash
    assert ge["contract_address"] == contract_address.lower()
    assert ge["project_id"] == "my-project"
    assert ge["block_number"] == 100
    # 21000 * 1_000_000_000 wei / 10**18 = 0.000021 USDC
    assert ge["usdc_gas_paid"] == "0.000021"

    assert len(token_flows) == 1
    tf = token_flows[0]
    assert tf["token_address"] == USDC_ADDRESS
    assert tf["from_address"] == "0x" + FROM_ADDR
    assert tf["to_address"] == "0x" + TO_ADDR
    assert tf["amount"] == "5"
    assert tf["block_number"] == 100


def test_process_block_no_project_match_is_none_not_error():
    tx_hash = "0xdef456"
    contract_address = "0x9999999999999999999999999999999999999"

    block = {
        "timestamp": 1_726_000_000,
        "transactions": [
            {"hash": FakeHex(tx_hash), "to": contract_address, "gasPrice": 1_000_000_000}
        ],
    }
    receipt = {"gasUsed": 21000, "effectiveGasPrice": 1_000_000_000, "logs": []}
    w3 = FakeW3(block, {tx_hash: receipt})

    gas_events, token_flows = process_block(w3, block_number=5, contract_project_map={})

    assert len(gas_events) == 1
    assert gas_events[0]["project_id"] is None
    assert token_flows == []


def test_process_block_ignores_untracked_token_logs():
    tx_hash = "0x111"
    contract_address = "0x8888888888888888888888888888888888888"

    block = {
        "timestamp": 1_726_000_000,
        "transactions": [
            {"hash": FakeHex(tx_hash), "to": contract_address, "gasPrice": 1_000_000_000}
        ],
    }
    untracked_log = _make_transfer_log(
        from_addr_hex40=FROM_ADDR,
        to_addr_hex40=TO_ADDR,
        raw_amount=1000,
    )
    untracked_log["address"] = "0x0000000000000000000000000000000000dead"  # not in TRACKED_TOKENS

    receipt = {"gasUsed": 21000, "effectiveGasPrice": 1_000_000_000, "logs": [untracked_log]}
    w3 = FakeW3(block, {tx_hash: receipt})

    _, token_flows = process_block(w3, block_number=5, contract_project_map={})
    assert token_flows == []
