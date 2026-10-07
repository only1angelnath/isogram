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
