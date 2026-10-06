"""
Tests for rollup.py - the rollup-based ingestion path. Pure/in-memory: no
network, no DB. Includes the decimal-conversion guarantees from
docs/BUGS.md #1 re-asserted for the new path.
"""

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rollup
from rollup import BatchAccumulator, RpcResultError, _raw_rpc_on_pool, run_rollup
from worker import TRANSFER_EVENT_TOPIC, _StickyPoolIndex

USDC = "0x3600000000000000000000000000000000000000"
SYSTEM = "0xfffffffffffffffffffffffffffffffffffffffe"
EURC = "0xbef5f6d51cb62b58e6a8f77868681825c6fe21c1"
SENDER_A = "0x" + "aa" * 20
SENDER_B = "0x" + "bb" * 20
CONTRACT = "0x" + "cc" * 20
TS = 1_790_000_000  # 2026-09-21 UTC-ish; only the DAY matters
DAY = "2026-09-21"


def _pad_addr(addr: str) -> str:
    return "0x" + "0" * 24 + addr[2:]


def receipt(frm=SENDER_A, to=CONTRACT, gas_used=21000, price=2 * 10**11, status="0x1", logs=None):
    r = {
        "from": frm, "to": to, "status": status,
        "gasUsed": hex(gas_used), "effectiveGasPrice": hex(price),
        "logs": logs or [],
    }
    return r


def usdc_transfer_log(raw_amount: int, token=USDC):
    return {
        "address": token,
        "topics": [TRANSFER_EVENT_TOPIC, _pad_addr(SENDER_A), _pad_addr(SENDER_B)],
        "data": hex(raw_amount),
    }


def system_log(raw_18dec: int, frm=None, to=None):
    """Native system Transfer (EIP-7708), 18 decimals, emitted for EVERY USDC movement."""
    zero = "0x" + "0" * 64
    return {
        "address": SYSTEM,
        "topics": [TRANSFER_EVENT_TOPIC, frm or _pad_addr(SENDER_A), to or _pad_addr(SENDER_B)],
        "data": hex(raw_18dec),
    }


def test_gas_matches_hand_calculation_6_decimal_view():
    # 21000 gas * 2e11 wei = 4.2e15 wei = 0.0042 USDC (18-dec native -> human USDC)
    acc = BatchAccumulator(set())
    acc.add_block(TS, [receipt()])
    assert acc.network[DAY]["usdc_gas_paid"] == Decimal("0.0042")
    assert acc.contracts[(DAY, CONTRACT)][2] == Decimal("0.0042")


def test_gas_and_usdc_volume_are_separate_quantities():
    # A tx that pays gas AND moves 1.5 USDC: gas stays gas, volume stays volume (BUGS.md #1).
    acc = BatchAccumulator(set())
    acc.add_block(TS, [receipt(logs=[system_log(15 * 10**17)])])
    assert acc.network[DAY]["usdc_gas_paid"] == Decimal("0.0042")
    assert acc.tokens[(DAY, USDC)] == [1, Decimal("1.5")]
    assert acc.network[DAY]["token_transfer_count"] == 1


def test_erc20_transfer_emits_both_streams_and_is_counted_ONCE():
    # Arc docs: one ERC-20 transfer() = a 6-dec log from 0x3600 AND an 18-dec system log.
    acc = BatchAccumulator(set())
    acc.add_block(TS, [receipt(logs=[system_log(25 * 10**17), usdc_transfer_log(2_500_000)])])
    assert acc.tokens[(DAY, USDC)] == [1, Decimal("2.5")]  # not 2 transfers / 5.0 USDC
    assert acc.network[DAY]["token_transfer_count"] == 1


def test_plain_native_send_is_counted_via_system_log_only():
    # No 0x3600 log at all - the stream we used before 2026-10-05 would have missed this.
    acc = BatchAccumulator(set())
    acc.add_block(TS, [receipt(logs=[system_log(10**18)])])
    assert acc.tokens[(DAY, USDC)] == [1, Decimal("1")]


def test_erc20_stream_alone_is_ignored_for_usdc():
    acc = BatchAccumulator(set())
    acc.add_block(TS, [receipt(logs=[usdc_transfer_log(1_500_000)])])
    assert acc.tokens == {} and acc.network[DAY]["token_transfer_count"] == 0


def test_mint_and_burn_system_logs_are_not_volume():
    zero = "0x" + "0" * 64
    acc = BatchAccumulator(set())
    acc.add_block(TS, [receipt(logs=[system_log(10**18, frm=zero)]), receipt(logs=[system_log(10**18, to=zero)])])
    assert acc.tokens == {}


def test_18_to_6_decimal_conversion_quantizes_in_payload():
    # 1.123456789012345678 USDC native -> stored at 6 decimals
    acc = BatchAccumulator(set())
    acc.add_block(TS, [receipt(logs=[system_log(1_123_456_789_012_345_678)])])
    p = acc.to_payload()["p_tokens"][0]
    assert p["token_address"] == USDC and p["volume"] == "1.123457" and p["transfer_count"] == 1


def test_failed_tx_and_contract_creation_counted():
    acc = BatchAccumulator(set())
    acc.add_block(TS, [receipt(status="0x0"), receipt(to=None)])
    net = acc.network[DAY]
    assert net["tx_count"] == 2 and net["failed_tx_count"] == 1 and net["contract_creations"] == 1
    assert acc.contracts[(DAY, CONTRACT)][:2] == [1, 1]
    # creation (to=None) pays gas but has no contract row
    assert len([k for k in acc.contracts]) == 1
    assert net["usdc_gas_paid"] == Decimal("0.0084")


def test_native_sentinel_recipient_counted_in_network_not_in_contracts():
    acc = BatchAccumulator(set())
    acc.add_block(TS, [receipt(to="0x" + "0" * 40)])
    assert acc.network[DAY]["tx_count"] == 1
    assert acc.contracts == {}


def test_senders_and_tracked_contract_users():
    acc = BatchAccumulator({CONTRACT})
    other = "0x" + "dd" * 20
    acc.add_block(TS, [receipt(frm=SENDER_A), receipt(frm=SENDER_A), receipt(frm=SENDER_B),
                       receipt(frm=SENDER_B, to=other)])
    assert acc.addresses[DAY] == {"aa" * 20, "bb" * 20}
    assert acc.contract_users[DAY][CONTRACT] == {"aa" * 20, "bb" * 20}
    assert other not in acc.contract_users[DAY]  # untracked contract: no per-contract users


def test_missing_from_is_counted_not_guessed():
    acc = BatchAccumulator(set())
    r = receipt()
    del r["from"]
    acc.add_block(TS, [r])
    assert acc.missing_from == 1 and acc.addresses == {}
    assert acc.network[DAY]["tx_count"] == 1


def test_missing_effective_gas_price_fails_loud():
    acc = BatchAccumulator(set())
    r = receipt()
    del r["effectiveGasPrice"]
    with pytest.raises(KeyError):
        acc.add_block(TS, [r])


def test_untracked_token_and_malformed_transfer_ignored():
    acc = BatchAccumulator(set())
    malformed = {"address": USDC, "topics": [TRANSFER_EVENT_TOPIC, _pad_addr(SENDER_A)], "data": "0x01"}
    acc.add_block(TS, [receipt(logs=[usdc_transfer_log(5, token="0x" + "ee" * 20), malformed, {"address": SYSTEM, "topics": [TRANSFER_EVENT_TOPIC], "data": "0x01"}])])
    assert acc.tokens == {} and acc.network[DAY]["token_transfer_count"] == 0


def test_eurc_tracked_with_6_decimals():
    acc = BatchAccumulator(set())
    acc.add_block(TS, [receipt(logs=[usdc_transfer_log(2_000_000, token=EURC)])])
    assert acc.tokens[(DAY, EURC)] == [1, Decimal("2")]


def test_order_independent_and_json_serialisable():
    blocks = [(TS, [receipt(frm=SENDER_A)]), (TS + 1, [receipt(frm=SENDER_B, status="0x0")]),
              (TS + 2, [receipt(logs=[system_log(10**18)])])]
    a, b = BatchAccumulator({CONTRACT}), BatchAccumulator({CONTRACT})
    for ts, rc in blocks:
        a.add_block(ts, rc)
    for ts, rc in reversed(blocks):
        b.add_block(ts, rc)

    def norm(p):
        return json.dumps(p, sort_keys=True, default=str)

    pa, pb = a.to_payload(), b.to_payload()
    for key in ("p_contracts", "p_network", "p_tokens"):
        pa[key] = sorted(pa[key], key=norm)
        pb[key] = sorted(pb[key], key=norm)
    assert norm(pa) == norm(pb)
    json.dumps(a.to_payload())  # must not raise (Decimals already strings)
    assert a.network[DAY]["blocks"] == 3


def test_day_boundary_splits_rollups():
    acc = BatchAccumulator(set())
    acc.add_block(1_790_000_000, [receipt()])
    acc.add_block(1_790_000_000 + 86_400, [receipt()])
    assert len(acc.network) == 2


# ----------------------------------------------------------- RPC rotation

class _Provider:
    def __init__(self, behaviours):
        self.behaviours = list(behaviours)
        self.calls = 0

    def make_request(self, method, params):
        self.calls += 1
        b = self.behaviours.pop(0) if len(self.behaviours) > 1 else self.behaviours[0]
        if isinstance(b, Exception):
            raise b
        return b


class _W3:
    def __init__(self, *behaviours):
        self.provider = _Provider(behaviours)


def _http_error(status):
    resp = requests.Response()
    resp.status_code = status
    return requests.exceptions.HTTPError(response=resp)


def test_rotates_past_unsupported_method_and_sticks(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    unsupported = _W3({"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "method not found"}})
    good = _W3({"jsonrpc": "2.0", "id": 1, "result": [1, 2]})
    sticky = _StickyPoolIndex()
    assert _raw_rpc_on_pool([unsupported, good], sticky, "eth_getBlockReceipts", ["0x1"]) == [1, 2]
    assert sticky.index == 1


def test_429_exhausts_retries_then_falls_to_next_endpoint(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    throttled = _W3(_http_error(429))
    good = _W3({"result": []})
    sticky = _StickyPoolIndex()
    assert _raw_rpc_on_pool([throttled, good], sticky, "eth_getBlockReceipts", ["0x1"]) == []
    assert throttled.provider.calls == 2  # RPC_RETRY_MAX_ATTEMPTS
    assert sticky.index == 1


def test_connection_error_falls_through_and_all_failing_raises(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    down = _W3(requests.exceptions.ConnectionError("boom"))
    nullres = _W3({"result": None})
    with pytest.raises((requests.exceptions.ConnectionError, RpcResultError)):
        _raw_rpc_on_pool([down, nullres], _StickyPoolIndex(), "eth_getBlockByNumber", ["0x1", False])


# ------------------------------------------------------------- run_rollup

class _FakeClient:
    def __init__(self, fail_on_call=None):
        self.calls = []
        self.fail_on_call = fail_on_call

    def rpc(self, fn, params):
        self.calls.append((fn, params))
        outer = self

        class _Exec:
            def execute(self_inner):
                if outer.fail_on_call is not None and len(outer.calls) == outer.fail_on_call:
                    raise RuntimeError("checkpoint mismatch")
                return type("R", (), {"data": None})()

        return _Exec()


def _patch_fetch(monkeypatch):
    monkeypatch.setattr(rollup, "fetch_block", lambda pool, sticky, n: (n, TS, [receipt()]))


def test_run_rollup_contiguous_atomic_subbatches(monkeypatch):
    _patch_fetch(monkeypatch)
    monkeypatch.setattr(rollup, "BATCH_BLOCKS", 100)
    client = _FakeClient()
    out = run_rollup(client, [object()], _StickyPoolIndex(), {}, last_synced=1000, latest_block=1250, max_blocks=10_000)
    ranges = [(p["p_start_block"], p["p_end_block"]) for fn, p in client.calls]
    assert ranges == [(1001, 1100), (1101, 1200), (1201, 1250)]
    assert out["checkpoint"] == 1250 and out["lag"] == 0 and out["blocks"] == 250
    # every sub-batch carries the whole rollup payload
    assert client.calls[0][1]["p_network"][0]["tx_count"] == 100


def test_run_rollup_respects_max_blocks_and_budget(monkeypatch):
    _patch_fetch(monkeypatch)
    monkeypatch.setattr(rollup, "BATCH_BLOCKS", 100)
    c1 = _FakeClient()
    out = run_rollup(c1, [object()], _StickyPoolIndex(), {}, 0, 10_000, max_blocks=250)
    assert out["checkpoint"] == 250 and out["lag"] == 9750

    monkeypatch.setattr(rollup, "RUN_TIME_BUDGET_SECONDS", -1)  # already over budget
    c2 = _FakeClient()
    out = run_rollup(c2, [object()], _StickyPoolIndex(), {}, 0, 10_000, max_blocks=10_000)
    assert len(c2.calls) == 1 and out["checkpoint"] == 100  # at least one batch, then stops


def test_run_rollup_apply_failure_propagates_and_stops(monkeypatch):
    _patch_fetch(monkeypatch)
    monkeypatch.setattr(rollup, "BATCH_BLOCKS", 100)
    client = _FakeClient(fail_on_call=2)
    with pytest.raises(RuntimeError):
        run_rollup(client, [object()], _StickyPoolIndex(), {}, 0, 500, max_blocks=500)
    assert len(client.calls) == 2  # never moved on to batch 3 after the failed apply


def test_process_batch_failure_aborts_without_apply(monkeypatch):
    def flaky(pool, sticky, n):
        if n == 3:
            raise RuntimeError("rpc dead")
        return n, TS, [receipt()]
    monkeypatch.setattr(rollup, "fetch_block", flaky)
    with pytest.raises(RuntimeError):
        rollup.process_batch([object()], _StickyPoolIndex(), [1, 2, 3, 4], set(), concurrency=2)
