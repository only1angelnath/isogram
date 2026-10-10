"""
worker.main(): a discovery failure must NOT fail the ingestion job (and so un-chain it),
but a real ingestion failure must still fail loudly. Regression for the 2026-10-07 incident
(every 55-min run was marked failed because discovery crashed afterwards).
"""

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rollup
import worker


@pytest.fixture(autouse=True)
def _no_real_market_data(monkeypatch):
    """worker.main() also runs the market-data refresh; never let these tests reach the network."""
    mod = types.ModuleType("market_data")
    mod.run_market_data_refresh = lambda: {"skipped": "stubbed in tests"}
    monkeypatch.setitem(sys.modules, "market_data", mod)


@pytest.fixture(autouse=True)
def _no_real_holders(monkeypatch):
    mod = types.ModuleType("holders")
    mod.run_holders_refresh = lambda: {"due": 0, "calls": 0, "updated": 0, "unindexed": 0, "stopped": None, "targets": 0}
    monkeypatch.setitem(sys.modules, "holders", mod)


def _fake_holders(monkeypatch, behaviour):
    mod = types.ModuleType("holders")
    mod.run_holders_refresh = behaviour
    monkeypatch.setitem(sys.modules, "holders", mod)


def _fake_market_data(monkeypatch, behaviour):
    mod = types.ModuleType("market_data")
    mod.run_market_data_refresh = behaviour
    monkeypatch.setitem(sys.modules, "market_data", mod)


def _fake_discovery(monkeypatch, behaviour):
    mod = types.ModuleType("discovery")
    mod.run_discovery = behaviour
    monkeypatch.setitem(sys.modules, "discovery", mod)


OK = {"touched": 3, "trending_seeded": 1, "classified": 2, "promoted": 0}


def test_discovery_crash_after_good_ingestion_does_not_fail_the_job(monkeypatch, capsys):
    monkeypatch.setattr(worker, "run", lambda: None)
    def boom():
        raise RuntimeError("canceling statement due to statement timeout")
    _fake_discovery(monkeypatch, boom)
    worker.main()                                    # must NOT raise
    out = capsys.readouterr().out
    assert "::warning title=Discovery failed::RuntimeError" in out and "statement timeout" in out


def test_ingestion_failure_still_raises_and_discovery_still_runs(monkeypatch):
    ran = []
    def bad_run():
        raise ValueError("rpc exploded")
    monkeypatch.setattr(worker, "run", bad_run)
    _fake_discovery(monkeypatch, lambda: ran.append(1) or OK)
    with pytest.raises(ValueError, match="rpc exploded"):
        worker.main()
    assert ran == [1]


def test_discovery_error_never_masks_the_ingestion_error(monkeypatch):
    def bad_run():
        raise ValueError("the REAL problem")
    monkeypatch.setattr(worker, "run", bad_run)
    def boom():
        raise RuntimeError("secondary")
    _fake_discovery(monkeypatch, boom)
    with pytest.raises(ValueError, match="the REAL problem"):
        worker.main()


def test_happy_path_prints_discovery_summary(monkeypatch, capsys):
    monkeypatch.setattr(worker, "run", lambda: None)
    _fake_discovery(monkeypatch, lambda: OK)
    worker.main()
    assert "Discovery: 3 touched, 1 seeded" in capsys.readouterr().out


def test_market_data_crash_after_good_ingestion_does_not_fail_the_job(monkeypatch, capsys):
    monkeypatch.setattr(worker, "run", lambda: None)
    _fake_discovery(monkeypatch, lambda: OK)
    def boom():
        raise RuntimeError("coingecko exploded")
    _fake_market_data(monkeypatch, boom)
    worker.main()                                    # must NOT raise
    out = capsys.readouterr().out
    assert "::warning title=Market data refresh failed::RuntimeError" in out and "Finished in" in out


def test_market_data_summary_is_printed(monkeypatch, capsys):
    monkeypatch.setattr(worker, "run", lambda: None)
    _fake_discovery(monkeypatch, lambda: OK)
    _fake_market_data(monkeypatch, lambda: {"targets": 430, "batches": 15, "returned": 300,
                                            "upserted": 300, "stopped": None})
    worker.main()
    assert "Market data: 300 of 430 tokens priced in 15 calls." in capsys.readouterr().out


def test_market_data_early_stop_is_reported(monkeypatch, capsys):
    monkeypatch.setattr(worker, "run", lambda: None)
    _fake_discovery(monkeypatch, lambda: OK)
    _fake_market_data(monkeypatch, lambda: {"targets": 430, "batches": 3, "returned": 60,
                                            "upserted": 60, "stopped": "rate_limited"})
    worker.main()
    assert "stopped early (rate_limited)" in capsys.readouterr().out


def test_market_data_summary_mentions_7d_volume_progress_and_failures(monkeypatch, capsys):
    monkeypatch.setattr(worker, "run", lambda: None)
    _fake_discovery(monkeypatch, lambda: OK)
    base = {"targets": 430, "batches": 15, "returned": 300, "upserted": 300, "stopped": None}
    _fake_market_data(monkeypatch, lambda: dict(base, volume_7d_updated=80, volume_7d_calls=80))
    worker.main()
    assert "7d volume refreshed for 80" in capsys.readouterr().out
    _fake_market_data(monkeypatch, lambda: dict(base, volume_7d_error="RuntimeError: table locked"))
    worker.main()
    assert "7d volume pass failed (RuntimeError: table locked)" in capsys.readouterr().out


def test_holder_crash_does_not_fail_the_job(monkeypatch, capsys):
    monkeypatch.setattr(worker, "run", lambda: None)
    _fake_discovery(monkeypatch, lambda: OK)
    def boom():
        raise RuntimeError("explorer exploded")
    _fake_holders(monkeypatch, boom)
    worker.main()                                    # must NOT raise
    out = capsys.readouterr().out
    assert "::warning title=Holder refresh failed::RuntimeError" in out and "Finished in" in out


def test_holder_summary_is_printed(monkeypatch, capsys):
    monkeypatch.setattr(worker, "run", lambda: None)
    _fake_discovery(monkeypatch, lambda: OK)
    _fake_holders(monkeypatch, lambda: {"due": 150, "calls": 150, "updated": 90, "unindexed": 60, "stopped": "time_budget", "targets": 780})
    worker.main()
    assert "Holders: 90 refreshed, 60 not indexed as tokens, 150 due of 780 tokens, 150 calls, stopped early (time_budget)." in capsys.readouterr().out


def test_a_market_data_crash_does_not_stop_the_holder_pass(monkeypatch, capsys):
    monkeypatch.setattr(worker, "run", lambda: None)
    _fake_discovery(monkeypatch, lambda: OK)
    ran = []
    def boom():
        raise RuntimeError("coingecko exploded")
    _fake_market_data(monkeypatch, boom)
    _fake_holders(monkeypatch, lambda: ran.append(1) or {"due": 0, "calls": 0, "updated": 0, "unindexed": 0, "stopped": None, "targets": 0})
    worker.main()
    assert ran == [1]


def test_market_data_does_not_run_after_a_real_ingestion_failure(monkeypatch):
    ran = []
    monkeypatch.setattr(worker, "run", lambda: (_ for _ in ()).throw(ValueError("rpc exploded")))
    _fake_discovery(monkeypatch, lambda: OK)
    _fake_market_data(monkeypatch, lambda: ran.append(1) or {"skipped": "x"})
    with pytest.raises(ValueError, match="rpc exploded"):
        worker.main()
    assert ran == []


# ----------------------------------------------------------------- maintenance

class _Exec:
    def __init__(self, data): self.data = data
    def execute(self): return self


class _MaintClient:
    def __init__(self, tail_chunks, fail=None):
        self.tail = list(tail_chunks); self.calls = []; self.fail = fail
    def rpc(self, fn, params):
        self.calls.append(fn)
        if fn == self.fail:
            raise RuntimeError("timeout")
        if fn == "prune_rollup_long_tail":
            return _Exec(self.tail.pop(0))
        return _Exec({"active_addresses_deleted": 0})


def test_maintenance_loops_until_nothing_is_left(monkeypatch):
    c = _MaintClient([{"long_tail_rows_deleted": 50000, "more": True},
                      {"long_tail_rows_deleted": 50000, "more": True},
                      {"long_tail_rows_deleted": 1200, "more": False}])
    rollup.run_maintenance(c)
    assert c.calls.count("prune_rollup_long_tail") == 3


def test_maintenance_is_capped_and_never_fatal(monkeypatch):
    monkeypatch.setattr(rollup, "MAINTENANCE_MAX_CHUNKS", 4)
    c = _MaintClient([{"long_tail_rows_deleted": 50000, "more": True}] * 10)
    rollup.run_maintenance(c)
    assert c.calls.count("prune_rollup_long_tail") == 4          # hard cap
    rollup.run_maintenance(_MaintClient([], fail="prune_rollup_long_tail"))   # must not raise
    rollup.run_maintenance(_MaintClient([{"long_tail_rows_deleted": 0, "more": False}], fail="prune_rollup_addresses"))

