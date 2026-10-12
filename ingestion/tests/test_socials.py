"""socials.py: parsing self-reported links, due-selection, caching of empty results, bounds and failures."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import socials as so

NOW = datetime(2026, 10, 9, 22, 0, tzinfo=timezone.utc)


def addr(i): return f"0x{i:040x}"


def info(**attrs): return {"data": {"attributes": attrs}}


def test_parse_info_takes_the_first_clean_website_and_the_handles():
    got = so.parse_info(info(websites=["", "  ", "https://argus.world", "https://other.example"], twitter_handle="arguspad",
                            telegram_handle="argus_chat", discord_url="https://discord.gg/abc123"))
    assert got == {"website": "https://argus.world", "twitter": "arguspad", "telegram": "argus_chat", "discord": "https://discord.gg/abc123"}


def test_parse_info_rejects_junk_without_crashing():
    assert so.parse_info(None) == {"website": None, "twitter": None, "telegram": None, "discord": None}
    assert so.parse_info({}) == so.parse_info("x") == so.parse_info({"data": None}) == so.parse_info(info())
    got = so.parse_info(info(websites="https://not-a-list.example", twitter_handle=12345, telegram_handle="has space",
                            discord_url="x" * 301))
    assert got == {"website": None, "twitter": None, "telegram": None, "discord": None}
    assert so.parse_info(info(websites=[None, 5, "https://a.example\nHost: evil"]))["website"] is None   # control characters


def test_clean_trims_caps_length_and_refuses_whitespace_inside():
    assert so.clean("  ok  ") == "ok" and so.clean("a b") is None and so.clean("") is None and so.clean(None) is None
    assert so.clean("x" * 300) == "x" * 300 and so.clean("x" * 301) is None


def test_pick_due_orders_never_fetched_then_oldest_and_skips_fresh_for_seven_days():
    state = {addr(1): (NOW - timedelta(days=2)).isoformat(), addr(2): (NOW - timedelta(days=30)).isoformat(),
             addr(3): (NOW - timedelta(days=8)).isoformat(), addr(4): None}
    got = so.pick_due([addr(i) for i in (1, 2, 3, 4, 5, 4)], state, NOW)
    assert addr(1) not in got and set(got[:2]) == {addr(4), addr(5)} and got[2:] == [addr(2), addr(3)]
    assert len(so.pick_due([addr(i) for i in range(500)], {}, NOW, limit=60)) == 60


class FakeClient:
    def __init__(self): self.upserts = []
    def table(self, name):
        assert name == "token_socials"
        outer = self
        class T:
            def upsert(self, row, on_conflict=None):
                outer.upserts.append((row, on_conflict)); return self
            def execute(self): return None
        return T()


def run(fetch, candidates, **kw):
    client = FakeClient()
    return client, so.refresh_socials(client, candidates, "KEY", fetch=fetch, sleep=lambda s: None, **kw)


def test_stores_links_and_caches_empty_and_404_as_all_null_rows():
    answers = {addr(1): (200, info(websites=["https://a.example"], twitter_handle="a")), addr(2): (200, info()), addr(3): (404, None)}
    client, s = run(lambda a, k: answers[a], [addr(1), addr(2), addr(3)])
    rows = {r["contract_address"]: r for r, _ in client.upserts}
    assert rows[addr(1)]["website"] == "https://a.example" and rows[addr(1)]["twitter"] == "a" and rows[addr(1)]["source"] == "geckoterminal"
    assert all(rows[addr(i)][c] is None for i in (2, 3) for c in ("website", "twitter", "telegram", "discord"))
    assert all(oc == "contract_address" and r["fetched_at"] for r, oc in client.upserts)
    assert (s["with_links"], s["empty"], s["calls"], s["stopped"]) == (1, 2, 3, None)


def test_errors_are_retried_next_run_and_a_429_or_budget_stops_the_pass():
    answers = iter([(0, None), (500, None), (200, info(twitter_handle="x"))])
    client, s = run(lambda a, k: next(answers), [addr(i) for i in range(3)])
    assert len(client.upserts) == 1 and s["calls"] == 3
    answers = iter([(200, info(twitter_handle="x")), (429, None), (200, info())])
    client, s = run(lambda a, k: next(answers), [addr(i) for i in range(3)])
    assert s["stopped"] == "rate_limited" and len(client.upserts) == 1
    now = {"t": 0.0}
    def fetch(a, k):
        now["t"] += 30
        return 200, info()
    client = FakeClient()
    s = so.refresh_socials(client, [addr(i) for i in range(10)], "KEY", fetch=fetch, clock=lambda: now["t"], sleep=lambda x: None, budget_seconds=60)
    assert s["stopped"] == "time_budget" and s["calls"] == 2


def test_fetch_info_uses_the_pro_info_endpoint_and_maps_failures(monkeypatch):
    seen = {}
    class Resp:
        status_code = 200
        def json(self): return {"data": {}}
    def fake_get(url, headers=None, timeout=None):
        seen.update(url=url, headers=headers); return Resp()
    monkeypatch.setattr(so.requests, "get", fake_get)
    assert so.fetch_info(addr(9), "KEY") == (200, {"data": {}})
    assert seen["url"] == f"https://pro-api.coingecko.com/api/v3/onchain/networks/arc/tokens/{addr(9)}/info"
    assert seen["headers"]["x-cg-pro-api-key"] == "KEY"
    monkeypatch.setattr(so.requests, "get", lambda *a, **k: (_ for _ in ()).throw(so.requests.Timeout("slow")))
    assert so.fetch_info(addr(1), "KEY") == (0, None)
    class Bad: status_code = 404
    monkeypatch.setattr(so.requests, "get", lambda *a, **k: Bad())
    assert so.fetch_info(addr(1), "KEY") == (404, None)
    class NotJson:
        status_code = 200
        def json(self): raise ValueError("no")
    monkeypatch.setattr(so.requests, "get", lambda *a, **k: NotJson())
    assert so.fetch_info(addr(1), "KEY") == (200, None)


def test_load_state_reads_past_the_1000_row_cap_and_run_skips_without_a_key(monkeypatch):
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
    assert len(so.load_state(C())) == 2300
    monkeypatch.delenv("COINGECKO_PRO_API_KEY", raising=False)
    assert "skipped" in so.run_socials_refresh()
