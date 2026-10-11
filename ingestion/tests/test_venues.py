"""venues.py: pool parsing, per-venue sums, scan stopping rules, and the 'only write a complete scan' guarantee."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import venues as v


def pool(dex, vol, name="A / USDC"):
    return {"attributes": {"name": name, "volume_usd": {"h24": str(vol)}}, "relationships": {"dex": {"data": {"id": dex}}}}


def page(*pools):
    return {"data": list(pools)}


def test_venue_kind_follows_the_confirmed_launchpad_list_only():
    for dex in ("argus", "faze", "foci", "o1-launchpad-arc", "long-supply"):
        assert v.venue_kind(dex) == "launchpad"
    for dex in ("uniswap-v3-arc", "uniswap-v4-arc", "aero-arc", "peach", "lunya", "arctide", "aka-fun", "minara-fun", "virtuals-arc", "never-heard-of-it"):
        assert v.venue_kind(dex) == "dex"            # unconfirmed names are NOT promoted to launchpad by guesswork


def test_parse_pool_reads_venue_volume_and_name_and_tolerates_junk():
    assert v.parse_pool(pool("Uniswap-V3-Arc", "2442610.5", "cirBTC / USDC 0.01%")) == {
        "dex_id": "uniswap-v3-arc", "name": "cirBTC / USDC 0.01%", "volume": 2442610.5}
    assert v.parse_pool(pool("x", None))["volume"] == 0.0
    assert v.parse_pool(pool("x", "garbage"))["volume"] == 0.0
    assert v.parse_pool(pool("x", "-5"))["volume"] == 0.0
    for bad in (None, {}, "x", {"relationships": {}}, {"relationships": {"dex": {"data": None}}},
                {"relationships": {"dex": {"data": {"id": "  "}}}}):
        assert v.parse_pool(bad) is None


def test_aggregate_sums_per_venue_counts_active_pools_and_finds_the_top_pool():
    pools = [v.parse_pool(p) for p in (pool("a", 100, "P1"), pool("a", 300, "P2"), pool("a", 0, "P3"), pool("b", 50, "Q1"))]
    rows = {r["dex_id"]: r for r in v.aggregate(pools, {"a": "Venue A", "b": "Venue B", "c": "Venue C"})}
    assert rows["a"]["volume_24h_usd"] == 400.0 and rows["a"]["active_pools"] == 2
    assert rows["a"]["top_pool_name"] == "P2" and rows["a"]["top_pool_volume_usd"] == 300.0
    assert rows["a"]["name"] == "Venue A" and rows["a"]["sample_pools"] == 4 and rows["a"]["source"] == "geckoterminal"
    assert rows["c"]["volume_24h_usd"] == 0.0 and rows["c"]["top_pool_name"] is None and rows["c"]["top_pool_volume_usd"] is None
    assert rows["b"]["kind"] == "dex"


def test_a_venue_seen_only_in_pools_falls_back_to_its_id_as_the_name():
    rows = v.aggregate([v.parse_pool(pool("mystery", 5))], {})
    assert rows[0]["name"] == "mystery"


# ------------------------------------------------------------------ scanning

def scan(pages_by_number, **kw):
    seen = []
    def fetch(n, key, sort):
        seen.append((n, sort))
        return pages_by_number(n, sort)
    pools, summary = v.collect_pools("KEY", fetch=fetch, **kw)
    return pools, summary, seen


def test_stops_when_the_volume_tail_reaches_zero_and_counts_as_complete():
    pools, s, seen = scan(lambda n, sort: (200, page(pool("a", 100), pool("a", 0))) if n == 1 else (200, page(pool("a", 0))))
    assert s["stopped"] == "volume_tail_reached" and s["complete"] and s["pages"] == 1 and len(seen) == 1
    assert len(pools) == 2


def test_stops_on_an_empty_page_as_complete():
    pools, s, _ = scan(lambda n, sort: (200, page(pool("a", 5))) if n == 1 else (200, page()))
    assert s["stopped"] == "no_more_pools" and s["complete"] and len(pools) == 1


def test_reaches_the_ten_page_cap_as_complete():
    pools, s, seen = scan(lambda n, sort: (200, page(pool("a", 10 + n))))
    assert s["stopped"] == "page_cap" and s["complete"] and s["pages"] == 10 and len(seen) == 10 and len(pools) == 10


def test_rate_limit_error_and_time_budget_are_incomplete():
    _, s, _ = scan(lambda n, sort: (200, page(pool("a", 5))) if n < 3 else (429, None))
    assert s["stopped"] == "rate_limited" and not s["complete"]
    _, s, _ = scan(lambda n, sort: (200, page(pool("a", 5))) if n < 2 else (500, None))
    assert s["stopped"] == "http_500" and not s["complete"]
    _, s, _ = scan(lambda n, sort: (0, None))
    assert s["stopped"] == "http_0" and not s["complete"]
    now = {"t": 0.0}
    def fetch(n, key, sort):
        now["t"] += 40
        return 200, page(pool("a", 5))
    _, s = v.collect_pools("KEY", fetch=fetch, clock=lambda: now["t"], budget_seconds=60)
    assert s["stopped"] == "time_budget" and not s["complete"]


def test_if_the_api_rejects_the_sort_parameter_it_retries_unsorted_and_scans_everything():
    def pages(n, sort):
        if sort:
            return 400, None
        return (200, page(pool("a", 0))) if n < 3 else (200, page())     # zero volume must NOT end an unsorted scan
    pools, s, seen = scan(pages)
    assert s["sorted"] is False and s["stopped"] == "no_more_pools" and s["complete"] and len(pools) == 2
    assert seen[0] == (1, v.SORT) and seen[1] == (1, None)


# ------------------------------------------------------------------ refresh + write guarantee

class FakeClient:
    def __init__(self): self.upserts = []
    def table(self, name):
        assert name == "venue_market_data"
        outer = self
        class T:
            def upsert(self, rows, on_conflict=None):
                outer.upserts.append((list(rows), on_conflict)); return self
            def execute(self): return None
        return T()


def test_a_complete_scan_is_written_with_names_kinds_and_a_timestamp():
    client = FakeClient()
    pages = {1: (200, page(pool("argus", 300, "ARC / USDC"), pool("uniswap-v3-arc", 700)))}
    s = v.refresh_venues(client, "KEY", fetch_names=lambda k: (200, {"argus": "Argus", "uniswap-v3-arc": "Uniswap V3 (Arc)", "foci": "Foci"}),
                         fetch_page=lambda n, k, sort: pages.get(n, (200, page())))
    rows, on_conflict = client.upserts[0]
    by = {r["dex_id"]: r for r in rows}
    assert on_conflict == "dex_id" and set(by) == {"argus", "uniswap-v3-arc", "foci"}
    assert by["argus"]["kind"] == "launchpad" and by["argus"]["name"] == "Argus" and by["argus"]["volume_24h_usd"] == 300.0
    assert by["uniswap-v3-arc"]["kind"] == "dex" and by["foci"]["volume_24h_usd"] == 0.0
    assert all(r["fetched_at"] for r in rows)
    assert s["written"] == 3 and s["total_volume_usd"] == 1000.0 and s["pools"] == 2


def test_an_incomplete_scan_writes_nothing_so_old_numbers_are_kept():
    client = FakeClient()
    s = v.refresh_venues(client, "KEY", fetch_names=lambda k: (200, {}),
                         fetch_page=lambda n, k, sort: (200, page(pool("a", 5))) if n == 1 else (429, None))
    assert client.upserts == [] and s["written"] == 0 and s["stopped"] == "rate_limited"


def test_no_pools_at_all_writes_nothing():
    client = FakeClient()
    s = v.refresh_venues(client, "KEY", fetch_names=lambda k: (200, {"a": "A"}), fetch_page=lambda n, k, sort: (200, page()))
    assert client.upserts == [] and s["written"] == 0


def test_a_names_failure_only_costs_pretty_names():
    client = FakeClient()
    v.refresh_venues(client, "KEY", fetch_names=lambda k: (500, {}), fetch_page=lambda n, k, sort: (200, page(pool("a", 5))) if n == 1 else (200, page()))
    assert client.upserts[0][0][0]["name"] == "a"


def test_http_helpers_use_the_pro_endpoints_and_map_failures(monkeypatch):
    seen = {}
    class Resp:
        status_code = 200
        def json(self): return {"data": [{"id": "Argus", "attributes": {"name": "Argus"}}, {"id": 5}, "junk"]}
    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params, headers=headers); return Resp()
    monkeypatch.setattr(v.requests, "get", fake_get)
    assert v.fetch_dex_names("KEY") == (200, {"argus": "Argus"})
    assert seen["url"].endswith("/onchain/networks/arc/dexes") and seen["headers"]["x-cg-pro-api-key"] == "KEY"
    assert v.fetch_pools_page(3, "KEY") == (200, Resp().json())
    assert seen["url"].endswith("/onchain/networks/arc/pools") and seen["params"] == {"page": 3, "sort": "h24_volume_usd_desc"}
    assert v.fetch_pools_page(1, "KEY", sort=None)[0] == 200 and seen["params"] == {"page": 1}
    monkeypatch.setattr(v.requests, "get", lambda *a, **k: (_ for _ in ()).throw(v.requests.Timeout("slow")))
    assert v.fetch_pools_page(1, "KEY") == (0, None)
    class Bad: status_code = 503
    monkeypatch.setattr(v.requests, "get", lambda *a, **k: Bad())
    assert v.fetch_pools_page(1, "KEY") == (503, None) and v.fetch_dex_names("KEY") == (503, {})
    class NotJson:
        status_code = 200
        def json(self): raise ValueError("no")
    monkeypatch.setattr(v.requests, "get", lambda *a, **k: NotJson())
    assert v.fetch_pools_page(1, "KEY") == (200, None)


def test_run_skips_quietly_without_a_key(monkeypatch):
    monkeypatch.delenv("COINGECKO_PRO_API_KEY", raising=False)
    assert "skipped" in v.run_venues_refresh()
