"""venues.py: pool parsing, the anomaly filter, per-venue scanning and the write guarantees."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import venues as v


def pool(vol, reserve=100_000, buyers=20, sellers=20, name="A / USDC", dex=None, h24=True):
    attrs = {"name": name, "volume_usd": {"h24": str(vol)}, "reserve_in_usd": str(reserve)}
    if h24:
        attrs["transactions"] = {"h24": {"buyers": buyers, "sellers": sellers, "buys": 5, "sells": 5}}
    item = {"attributes": attrs}
    if dex:
        item["relationships"] = {"dex": {"data": {"id": dex}}}
    return item


def page(*pools):
    return {"data": list(pools)}


def parsed(vol, reserve=100_000, traders=40, name="A / USDC", dex="d"):
    return {"dex_id": dex, "name": name, "volume": float(vol), "reserve": float(reserve), "traders": traders}


# ------------------------------------------------------------------ kinds + parsing

def test_venue_kind_follows_the_confirmed_launchpad_list_only():
    for dex in ("argus", "faze", "foci", "o1-launchpad-arc", "long-supply"):
        assert v.venue_kind(dex) == "launchpad"
    for dex in ("uniswap-v3-arc", "uniswap-v4-arc", "aero-arc", "peach", "lunya", "arctide", "aka-fun", "minara-fun", "virtuals-arc", "x"):
        assert v.venue_kind(dex) == "dex"


def test_parse_pool_reads_volume_reserve_and_traders():
    p = v.parse_pool(pool(2442610.5, 11431941, 3000, 11, "cirBTC / USDC"), "Uniswap-V3-Arc")
    assert p == {"dex_id": "uniswap-v3-arc", "name": "cirBTC / USDC", "volume": 2442610.5, "reserve": 11431941.0, "traders": 3011}


def test_parse_pool_missing_pieces_are_handled_not_guessed():
    assert v.parse_pool(pool(5, h24=False), "d")["traders"] is None                    # no transaction counts at all
    assert v.parse_pool({"attributes": {"volume_usd": {"h24": "5"}, "transactions": {"h24": {"buyers": 3}}}}, "d")["traders"] is None
    assert v.parse_pool(pool("garbage", "junk"), "d")["volume"] == 0.0
    assert v.parse_pool(pool(-5), "d")["volume"] == 0.0
    assert v.parse_pool(pool(5, dex="from-relationship"))["dex_id"] == "from-relationship"
    for bad in (None, {}, "x"):
        assert v.parse_pool(bad, "d") is None or bad == {}                              # {} still has a dex id when one is passed
    assert v.parse_pool({}, None) is None and v.parse_pool(None) is None


# ------------------------------------------------------------------ the anomaly filter

def test_pools_with_too_few_traders_are_excluded_at_exactly_the_threshold():
    assert v.classify_pool(parsed(1000, traders=9)) == "excluded"
    assert v.classify_pool(parsed(1000, traders=10)) == "kept"
    assert v.classify_pool(parsed(1000, traders=3)) == "excluded"


def test_pools_whose_volume_dwarfs_their_reserves_are_excluded_at_exactly_the_threshold():
    assert v.classify_pool(parsed(25_000, reserve=1000)) == "kept"                 # 25x: allowed
    assert v.classify_pool(parsed(25_001, reserve=1000)) == "excluded"
    assert v.classify_pool(parsed(10, reserve=0)) == "excluded"                    # volume with no reserves at all


def test_zero_volume_pools_are_kept_and_pools_without_transaction_data_are_unknown():
    assert v.classify_pool(parsed(0, traders=0)) == "kept"
    assert v.classify_pool(parsed(500, traders=None)) == "unknown"


def test_the_real_uniswap_v4_pattern_from_2026_10_09():
    pools = [parsed(4_318_990, 38_971_336, traders=3, name="cirBTC / USDC"),       # 8 trades from 3 wallets
             parsed(100_000, 1_000, traders=50, name="DUST / USDC"),               # 100x turnover
             parsed(200_000, 500_000, traders=80, name="REAL / USDC")]
    row = v.aggregate(pools, {"d": "Uniswap V4 (Arc)"})[0]
    assert row["volume_24h_usd"] == 200_000.0 and row["excluded_volume_usd"] == 4_418_990.0
    assert row["excluded_pools"] == 2 and row["active_pools"] == 1 and row["top_pool_name"] == "REAL / USDC"


def test_aggregate_counts_unknown_pools_as_excluded_and_passes_truncation_through():
    pools = [parsed(300, traders=50, name="P1"), parsed(100, traders=None, name="P2"), parsed(0, traders=0, name="P3")]
    row = v.aggregate(pools, {"d": "Venue D"}, {"d": {"truncated": True}})[0]
    assert (row["volume_24h_usd"], row["excluded_volume_usd"], row["excluded_pools"]) == (300.0, 100.0, 1)
    assert row["truncated"] is True and row["sample_pools"] == 3 and row["name"] == "Venue D" and row["kind"] == "dex"


def test_aggregate_includes_scanned_venues_with_no_pools_and_falls_back_to_the_id_for_names():
    rows = {r["dex_id"]: r for r in v.aggregate([], {}, {"quiet": {"truncated": False}})}
    assert rows["quiet"]["volume_24h_usd"] == 0.0 and rows["quiet"]["name"] == "quiet" and rows["quiet"]["top_pool_name"] is None


def test_thresholds_can_be_overridden_for_the_preview():
    pools = [parsed(1000, traders=7)]
    assert v.aggregate(pools, {}, None)[0]["volume_24h_usd"] == 0.0
    assert v.aggregate(pools, {}, None, min_traders=5)[0]["volume_24h_usd"] == 1000.0


# ------------------------------------------------------------------ scanning one venue

def scan(pages, **kw):
    seen = []
    def fetch(dex, n, key, sort):
        seen.append((dex, n, sort))
        return pages(n, sort)
    pools, outcome = v.scan_venue("argus", "KEY", fetch=fetch, **kw)
    return pools, outcome, seen


def test_a_venue_ends_at_the_volume_tail_on_an_empty_page_or_the_cap():
    pools, o, seen = scan(lambda n, s: (200, page(pool(100), pool(0))))
    assert o["status"] == "complete" and not o["truncated"] and o["calls"] == 1 and len(pools) == 2
    pools, o, _ = scan(lambda n, s: (200, page(pool(5))) if n == 1 else (200, page()))
    assert o["status"] == "complete" and not o["truncated"] and len(pools) == 1
    pools, o, seen = scan(lambda n, s: (200, page(pool(50 + n))))
    assert o["status"] == "complete" and o["truncated"] and o["calls"] == 10 and len(pools) == 10
    pools, o, _ = scan(lambda n, s: (200, page(pool(50))), max_pages=3)
    assert o["truncated"] and o["calls"] == 3


def test_pools_are_attributed_to_the_venue_being_scanned():
    pools, _, _ = scan(lambda n, s: (200, page(pool(9))) if n == 1 else (200, page()))
    assert pools[0]["dex_id"] == "argus"


def test_rate_limit_and_errors_end_a_venue_scan_unfinished():
    _, o, _ = scan(lambda n, s: (200, page(pool(5))) if n < 3 else (429, None))
    assert o["status"] == "rate_limited"
    _, o, _ = scan(lambda n, s: (500, None))
    assert o["status"] == "error"
    _, o, _ = scan(lambda n, s: (200, None))
    assert o["status"] == "error"


def test_if_the_api_rejects_the_sort_parameter_the_venue_is_scanned_unsorted_and_flagged_truncated_at_the_cap():
    def pages(n, sort):
        return (400, None) if sort else (200, page(pool(0)))        # zero volume must NOT end an unsorted scan
    pools, o, seen = scan(pages)
    assert o["calls"] == 11 and o["sorted"] is False and o["truncated"] and len(pools) == 10
    assert seen[0] == ("argus", 1, v.SORT) and seen[1] == ("argus", 1, None)


# ------------------------------------------------------------------ refresh + write guarantees

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


def names(*ids): return lambda k: (200, {i: i.title() for i in ids})


def test_refresh_writes_every_completed_venue_with_filtered_and_excluded_volume():
    client = FakeClient()
    data = {"argus": [pool(300, 100_000, 30, 30), pool(900, 1_000_000, 1, 1)], "foci": []}
    s = v.refresh_venues(client, "KEY", fetch_names=names("argus", "foci", "uniswap-v4-arc"),
                         fetch_page=lambda dex, n, k, sort: (200, page(*data.get(dex, [])) if n == 1 else page()))
    rows, on_conflict = client.upserts[0]
    by = {r["dex_id"]: r for r in rows}
    assert on_conflict == "dex_id" and set(by) == {"argus", "foci", "uniswap-v4-arc"}
    assert by["argus"]["volume_24h_usd"] == 300.0 and by["argus"]["excluded_volume_usd"] == 900.0 and by["argus"]["kind"] == "launchpad"
    assert by["foci"]["volume_24h_usd"] == 0.0 and by["uniswap-v4-arc"]["volume_24h_usd"] == 0.0
    assert all(r["fetched_at"] for r in rows)
    assert (s["written"], s["kept_usd"], s["excluded_usd"], s["stopped"], s["incomplete"]) == (3, 300.0, 900.0, None, [])


def test_a_failing_venue_is_skipped_and_keeps_its_previous_row_while_the_rest_are_written():
    client = FakeClient()
    def fetch(dex, n, k, sort):
        if dex == "bad":
            return 500, None
        return (200, page(pool(100))) if n == 1 else (200, page())
    s = v.refresh_venues(client, "KEY", fetch_names=names("good", "bad"), fetch_page=fetch)
    assert [r["dex_id"] for r in client.upserts[0][0]] == ["good"] and s["incomplete"] == ["bad"] and s["written"] == 1


def test_a_rate_limit_stops_the_run_but_keeps_venues_already_finished():
    client = FakeClient()
    def fetch(dex, n, k, sort):
        if dex == "b":
            return 429, None
        return (200, page(pool(10))) if n == 1 else (200, page())
    s = v.refresh_venues(client, "KEY", fetch_names=names("a", "b", "c"), fetch_page=fetch)
    assert [r["dex_id"] for r in client.upserts[0][0]] == ["a"] and s["stopped"] == "rate_limited"


def test_the_time_budget_stops_the_run_between_venues():
    client = FakeClient()
    now = {"t": 0.0}
    def fetch(dex, n, k, sort):
        now["t"] += 50
        return (200, page(pool(10))) if n == 1 else (200, page())
    s = v.refresh_venues(client, "KEY", fetch_names=names("a", "b", "c", "d"), fetch_page=fetch,
                         clock=lambda: now["t"], budget_seconds=120)
    assert s["stopped"] == "time_budget" and 0 < s["written"] < 4


def test_no_venue_list_writes_nothing():
    client = FakeClient()
    s = v.refresh_venues(client, "KEY", fetch_names=lambda k: (500, {}), fetch_page=lambda *a: (200, page()))
    assert client.upserts == [] and s["written"] == 0 and s["stopped"] == "venue_list_http_500"


def test_a_venue_without_any_transaction_counts_is_refused_not_reported_unfiltered():
    client = FakeClient()
    s = v.refresh_venues(client, "KEY", fetch_names=names("argus", "faze"),
                         fetch_page=lambda dex, n, k, sort: (200, page(pool(500, h24=False)) if dex == "argus" and n == 1
                                                             else page(pool(500)) if n == 1 else page()))
    assert [r["dex_id"] for r in client.upserts[0][0]] == ["faze"] and s["incomplete"] == ["argus"]


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
    v.fetch_venue_page("uniswap-v4-arc", 3, "KEY")
    assert seen["url"].endswith("/onchain/networks/arc/dexes/uniswap-v4-arc/pools") and seen["params"] == {"page": 3, "sort": "h24_volume_usd_desc"}
    v.fetch_venue_page("argus", 1, "KEY", sort=None)
    assert seen["params"] == {"page": 1}
    monkeypatch.setattr(v.requests, "get", lambda *a, **k: (_ for _ in ()).throw(v.requests.Timeout("slow")))
    assert v.fetch_venue_page("argus", 1, "KEY") == (0, None)
    class Bad: status_code = 503
    monkeypatch.setattr(v.requests, "get", lambda *a, **k: Bad())
    assert v.fetch_venue_page("argus", 1, "KEY") == (503, None) and v.fetch_dex_names("KEY") == (503, {})
    class NotJson:
        status_code = 200
        def json(self): raise ValueError("no")
    monkeypatch.setattr(v.requests, "get", lambda *a, **k: NotJson())
    assert v.fetch_venue_page("argus", 1, "KEY") == (200, None)


def test_run_skips_quietly_without_a_key(monkeypatch):
    monkeypatch.delenv("COINGECKO_PRO_API_KEY", raising=False)
    assert "skipped" in v.run_venues_refresh()
