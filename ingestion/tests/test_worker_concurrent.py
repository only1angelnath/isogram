"""
Additional tests for worker.py's process_blocks_concurrent() — the
docs/BUGS.md #5 fix. The pre-existing 5 tests in test_worker.py only ever
exercise process_block() (single block, sequential); none of them touch
the new concurrent multi-block path at all, so a separate FakeW3 that
supports multiple blocks is needed here.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from worker import process_blocks_concurrent, TRANSFER_EVENT_TOPIC


class FakeHex:
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


class FakeW3EthMultiBlock:
    """Unlike test_worker.py's FakeW3Eth (single block), this supports
    multiple blocks keyed by block_number, matching what
    process_blocks_concurrent() actually calls get_block() with."""

    def __init__(self, blocks_by_number: dict, receipts_by_hash: dict):
        self._blocks_by_number = blocks_by_number
        self._receipts_by_hash = receipts_by_hash

    def get_block(self, block_number, full_transactions=True):
        return self._blocks_by_number[block_number]

    def get_transaction_receipt(self, tx_hash):
        return self._receipts_by_hash[tx_hash]


class FakeW3MultiBlock:
    def __init__(self, blocks_by_number, receipts_by_hash):
        self.eth = FakeW3EthMultiBlock(blocks_by_number, receipts_by_hash)


USDC_ADDRESS = "0x3600000000000000000000000000000000000000"


def _make_transfer_log(from_addr_hex40, to_addr_hex40, raw_amount, token_address=USDC_ADDRESS):
    topic_from = "0x" + "0" * 24 + from_addr_hex40
    topic_to = "0x" + "0" * 24 + to_addr_hex40
    return {
        "address": token_address,
        "topics": [FakeHex(TRANSFER_EVENT_TOPIC), FakeHex(topic_from), FakeHex(topic_to)],
        "data": FakeHex(hex(raw_amount)),
    }


FROM_ADDR = "1" * 39 + "a"
TO_ADDR = "2" * 39 + "b"


def test_process_blocks_concurrent_aggregates_across_multiple_blocks():
    """The core thing this function needs to get right: results from
    several blocks, each with several transactions, all correctly
    attributed to their own block_number/ts — not scrambled by fetching
    receipts concurrently instead of in block order."""
    contract_a = "0x1111111111111111111111111111111111111111"
    contract_b = "0x2222222222222222222222222222222222222222"

    blocks_by_number = {
        100: {
            "timestamp": 1_726_000_000,
            "transactions": [
                {"hash": FakeHex("0xaaa"), "to": contract_a, "gasPrice": 1_000_000_000},
                {"hash": FakeHex("0xbbb"), "to": contract_b, "gasPrice": 1_000_000_000},
            ],
        },
        101: {
            "timestamp": 1_726_000_012,  # ~12s later, one block on
            "transactions": [
                {"hash": FakeHex("0xccc"), "to": contract_a, "gasPrice": 1_000_000_000},
            ],
        },
    }
    receipts_by_hash = {
        "0xaaa": {
            "gasUsed": 21000, "effectiveGasPrice": 1_000_000_000,
            "logs": [_make_transfer_log(FROM_ADDR, TO_ADDR, 1_000_000)],  # 1 USDC
        },
        "0xbbb": {"gasUsed": 21000, "effectiveGasPrice": 1_000_000_000, "logs": []},
        "0xccc": {
            "gasUsed": 21000, "effectiveGasPrice": 1_000_000_000,
            "logs": [_make_transfer_log(FROM_ADDR, TO_ADDR, 2_000_000)],  # 2 USDC
        },
    }
    w3 = FakeW3MultiBlock(blocks_by_number, receipts_by_hash)
    contract_project_map = {contract_a.lower(): "project-a", contract_b.lower(): "project-b"}

    gas_events, token_flows = process_blocks_concurrent(
        w3, block_numbers=[100, 101], contract_project_map=contract_project_map
    )

    # 3 transactions total across 2 blocks -> 3 gas events, correctly
    # attributed to their own block_number regardless of fetch order.
    assert len(gas_events) == 3
    by_hash = {ge["tx_hash"]: ge for ge in gas_events}
    assert by_hash["0xaaa"]["block_number"] == 100
    assert by_hash["0xaaa"]["project_id"] == "project-a"
    assert by_hash["0xbbb"]["block_number"] == 100
    assert by_hash["0xbbb"]["project_id"] == "project-b"
    assert by_hash["0xccc"]["block_number"] == 101
    assert by_hash["0xccc"]["project_id"] == "project-a"

    # 2 of the 3 transactions had a Transfer log (0xbbb had none).
    assert len(token_flows) == 2
    amounts = sorted(tf["amount"] for tf in token_flows)
    assert amounts == ["1", "2"]


def test_process_blocks_concurrent_empty_block_range():
    """No blocks to process -> no crash, empty results."""
    w3 = FakeW3MultiBlock({}, {})
    gas_events, token_flows = process_blocks_concurrent(w3, block_numbers=[], contract_project_map={})
    assert gas_events == []
    assert token_flows == []


def test_process_blocks_concurrent_matches_sequential_process_block():
    """Regression guard: running the same single block through the new
    concurrent path must produce identical output to the old sequential
    process_block() — same shape, same values, just fetched differently."""
    from worker import process_block

    contract_address = "0x3333333333333333333333333333333333333333"
    block = {
        "timestamp": 1_726_000_000,
        "transactions": [
            {"hash": FakeHex("0xddd"), "to": contract_address, "gasPrice": 1_000_000_000},
        ],
    }
    receipt = {
        "gasUsed": 21000, "effectiveGasPrice": 1_000_000_000,
        "logs": [_make_transfer_log(FROM_ADDR, TO_ADDR, 5_000_000)],
    }

    class SingleBlockEth:
        def get_block(self, block_number, full_transactions=True):
            return block
        def get_transaction_receipt(self, tx_hash):
            return receipt
    class SingleBlockW3:
        def __init__(self):
            self.eth = SingleBlockEth()

    contract_project_map = {contract_address.lower(): "proj"}

    seq_gas, seq_flows = process_block(SingleBlockW3(), 100, contract_project_map)

    blocks_by_number = {100: block}
    receipts_by_hash = {"0xddd": receipt}
    conc_gas, conc_flows = process_blocks_concurrent(
        FakeW3MultiBlock(blocks_by_number, receipts_by_hash), [100], contract_project_map
    )

    assert seq_gas == conc_gas
    assert seq_flows == conc_flows
