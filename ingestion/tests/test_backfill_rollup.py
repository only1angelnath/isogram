"""backfill_rollup.run(): reads its own checkpoint state, stops at range_end, reports done."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backfill_rollup
import rollup

TS = 1_790_000_000


class _Exec:
    def __init__(self, data=None): self.data = data
    def execute(self): return self


class _Table:
    def __init__(self, state): self.state = state
    def select(self, *a): return self
    def eq(self, *a): return self
    def execute(self): return _Exec(self.state)


class _Client:
    def __init__(self, state):
        self.state, self.calls = state, []
    def table(self, name):
        assert name == "historical_backfill_state"
        return _Table(self.state)
    def rpc(self, fn, params):
        self.calls.append((fn, params))
        return _Exec(None)


def _wire(monkeypatch, state):
    client = _Client(state)
    monkeypatch.setattr(backfill_rollup, "get_client", lambda: client)
    monkeypatch.setattr(backfill_rollup, "load_contract_project_map", lambda c: {})
    monkeypatch.setattr(backfill_rollup, "get_web3_pool", lambda: [object()])
    monkeypatch.setattr(rollup, "fetch_block", lambda pool, sticky, n: (n, TS + n, [{
        "from": "0x" + "aa" * 20, "to": "0x" + "cc" * 20, "status": "0x1", "gasUsed": hex(21000),
        "effectiveGasPrice": hex(2 * 10**11), "logs": []}]))
    monkeypatch.setattr(rollup, "BATCH_BLOCKS", 100)
    return client


def test_run_processes_whole_range_and_reports_done(monkeypatch):
    client = _wire(monkeypatch, [{"range_start": 1000, "range_end": 1249, "next_block": 1000}])
    assert backfill_rollup.run() is True
    ranges = [(p["p_start_block"], p["p_end_block"]) for fn, p in client.calls if fn == "apply_backfill_batch"]
    assert ranges == [(1000, 1099), (1100, 1199), (1200, 1249)]


def test_run_resumes_from_next_block(monkeypatch):
    client = _wire(monkeypatch, [{"range_start": 1000, "range_end": 1249, "next_block": 1150}])
    assert backfill_rollup.run() is True
    assert client.calls[0][1]["p_start_block"] == 1150          # does not redo finished work


def test_run_reports_not_done_when_time_budget_ends_first(monkeypatch):
    client = _wire(monkeypatch, [{"range_start": 1000, "range_end": 1999, "next_block": 1000}])
    monkeypatch.setattr(rollup, "RUN_TIME_BUDGET_SECONDS", -1)   # stop after the first batch
    assert backfill_rollup.run() is False
    assert len(client.calls) == 1


def test_run_is_a_noop_when_already_complete(monkeypatch):
    client = _wire(monkeypatch, [{"range_start": 1000, "range_end": 1249, "next_block": 1250}])
    assert backfill_rollup.run() is True and client.calls == []


def test_run_fails_loudly_when_state_was_never_initialised(monkeypatch):
    _wire(monkeypatch, [])
    with pytest.raises(RuntimeError, match="start_gap_backfill"):
        backfill_rollup.run()
