"""holders.py: parsing, due-selection, negative caching, bounds and failure handling. No network or database."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import holders as h

NOW = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)


def addr(i):
    return f"0x{i:040x}"


def test_parse_holders_accepts_numbers_and_numeric_strings_only():
    assert h.parse_holders({"holders_count": 2521}) == 2521
    assert h.parse_holders({"holders_count": "2521"}) == 2521
    assert h.parse_holders({"holders_count": " 8 "}) == 8
    assert h.parse_holders({"holders_count": 0}) == 0
    for bad in (None, {}, [], "x", {"holders_count": None}, {"holders_count": "-3"}, {"holders_count": -3},
                {"holders_count": "1.5"}, {"holders_count": True}, {"holders_count": "12abc"}):
        assert h.parse_holders(bad) is None


def test_pick_due_orders_never_fetched_then_oldest_and_skips_fresh():
    state = {
        addr(1): (NOW - timedelta(hours=1)).isoformat(),     # fresh
        addr(2): (NOW - timedelta(hours=40)).isoformat(),    # oldest
        addr(3): (NOW - timedelta(hours=13)).isoformat(),
        addr(4): None,
        addr(5): "garbage",
    }
    got = h.pick_due([addr(i) for i in (1, 2, 3, 4, 5, 6, 4)], state, NOW)
    assert addr(1) not in got and got.count(addr(4)) == 1
    assert set(got[:3]) == {addr(4), addr(5), addr(6)}                       # never fetched / unreadable / unknown first
    assert got[3:] == [addr(2), addr(3)]                                      # then oldest first


def test_pick_due_is_capped_and_reads_naive_timestamps_as_utc():
    assert len(h.pick_due([addr(i) for i in range(500)], {}, NOW, limit=150)) == 150
    state = {addr(1): (NOW - timedelta(hours=2)).replace(tzinfo=None).isoformat()}
    assert h.pick_due([addr(1)], state, NOW) == []


class FakeClient:
    def __init__(self): self.upserts = []
    def table(self, name):
        assert name == "token_holders"
        outer = self
        class T:
            def upsert(self, row, on_conflict=None):
                outer.upserts.append((row, on_conflict)); return self
            def execute(self): return None
        return T()


def run(fetch, candidates, **kw):
    client = FakeClient()
    summary = h.refresh_holders(client, candidates, fetch=fetch, sleep=lambda s: None, **kw)
    return client, summary


def test_stores_counts_and_caches_404_as_null():
    answers = {addr(1): (200, {"holders_count": "2521"}), addr(2): (404, None), addr(3): (200, {"name": "no count"})}
    client, s = run(lambda a: answers[a], [addr(1), addr(2), addr(3)])
    rows = {r["contract_address"]: r for r, _ in client.upserts}
    assert rows[addr(1)]["holders_count"] == 2521 and rows[addr(1)]["source"] == "explorer.arc.io"
    assert rows[addr(2)]["holders_count"] is None and rows[addr(3)]["holders_count"] is None
    assert all(oc == "contract_address" and r["fetched_at"] for r, oc in client.upserts)
    assert (s["updated"], s["unindexed"], s["calls"], s["stopped"]) == (1, 2, 3, None)


def test_network_errors_and_server_errors_are_skipped_and_retried_next_run():
    answers = iter([(0, None), (500, None), (502, None), (200, {"holders_count": 5})])
    client, s = run(lambda a: next(answers), [addr(i) for i in range(4)])
    assert len(client.upserts) == 1 and s["updated"] == 1 and s["calls"] == 4      # failures wrote nothing


def test_rate_limit_stops_the_pass_but_keeps_earlier_results():
    answers = iter([(200, {"holders_count": 1}), (429, None), (200, {"holders_count": 9})])
    client, s = run(lambda a: next(answers), [addr(i) for i in range(3)])
    assert s["stopped"] == "rate_limited" and s["calls"] == 2 and len(client.upserts) == 1


def test_time_budget_stops_the_pass():
    now = {"t": 0.0}
    def fetch(a):
        now["t"] += 40
        return 200, {"holders_count": 1}
    client = FakeClient()
    s = h.refresh_holders(client, [addr(i) for i in range(10)], fetch=fetch, clock=lambda: now["t"],
                          sleep=lambda x: None, budget_seconds=90)
    assert s["stopped"] == "time_budget" and s["calls"] == 3


def test_fetch_token_uses_the_explorer_with_a_browser_user_agent(monkeypatch):
    seen = {}
    class Resp:
        status_code = 200
        def json(self): return {"holders_count": "7"}
    def fake_get(url, headers=None, timeout=None):
        seen.update(url=url, headers=headers, timeout=timeout); return Resp()
    monkeypatch.setattr(h.requests, "get", fake_get)
    assert h.fetch_token(addr(9)) == (200, {"holders_count": "7"})
    assert seen["url"] == f"https://explorer.arc.io/api/v2/tokens/{addr(9)}"
    assert "Mozilla" in seen["headers"]["User-Agent"] and seen["timeout"] == h.REQUEST_TIMEOUT_SECONDS


def test_fetch_token_maps_failures(monkeypatch):
    monkeypatch.setattr(h.requests, "get", lambda *a, **k: (_ for _ in ()).throw(h.requests.Timeout("slow")))
    assert h.fetch_token(addr(1)) == (0, None)
    class Bad: status_code = 404
    monkeypatch.setattr(h.requests, "get", lambda *a, **k: Bad())
    assert h.fetch_token(addr(1)) == (404, None)
    class NotJson:
        status_code = 200
        def json(self): raise ValueError("no")
    monkeypatch.setattr(h.requests, "get", lambda *a, **k: NotJson())
    assert h.fetch_token(addr(1)) == (200, None)


def test_load_state_reads_past_the_1000_row_cap():
    rows = [{"contract_address": addr(i), "fetched_at": None} for i in range(2300)]
    class Q:
        def __init__(s): s.after = None; s.n = None
        def select(s, *a): return s
        def gt(s, c, v): s.after = v; return s
        def order(s, *a): return s
        def limit(s, n): s.n = n; return s
        def execute(s):
            d = sorted((r for r in rows if s.after is None or r["contract_address"] > s.after), key=lambda r: r["contract_address"])[: s.n]
            return type("R", (), {"data": d})()
    class C:
        def table(s, n): return Q()
    assert len(h.load_state(C())) == 2300
