"""
market_data.py: parsing GeckoTerminal payloads, choosing which projects to price, batching,
and failure handling - all without a network or database. Also pins that the priced
categories stay identical to the token + stablecoin segments in scoring/segments.py.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import market_data as md

SEGMENTS = Path(__file__).resolve().parents[2] / "scoring" / "segments.py"


def addr(i):
    return f"0x{i:040x}"


def payload(*items):
    return {"data": [{"attributes": a} for a in items]}


# ------------------------------------------------------------------ parsing

def test_num_accepts_finite_non_negative_numbers_only():
    assert md._num("0.5") == 0.5 and md._num(3) == 3.0 and md._num("2.4e-06") == pytest.approx(2.4e-06)
    for bad in (None, "", "abc", "NaN", "inf", "-inf", "-1", -0.0001):
        assert md._num(bad) is None


def test_parse_token_rows_full_row():
    rows = md.parse_token_rows(payload({
        "address": "0xABCDEF" + "0" * 34, "symbol": "USDC", "price_usd": "0.9997",
        "fdv_usd": "5.2e8", "market_cap_usd": None, "total_reserve_in_usd": "14621800.5",
        "volume_usd": {"h24": "56838400"}, "coingecko_coin_id": " usd-coin ",
    }))
    r = rows["0xabcdef" + "0" * 34]
    assert r == {
        "contract_address": "0xabcdef" + "0" * 34, "symbol": "USDC", "coingecko_coin_id": "usd-coin",
        "price_usd": 0.9997,
        "fdv_usd": 5.2e8, "market_cap_usd": None, "liquidity_usd": 14621800.5,
        "volume_24h_usd": 56838400.0, "source": "geckoterminal",
    }


def test_missing_or_blank_coin_id_is_none():
    rows = md.parse_token_rows(payload(
        {"address": addr(1), "price_usd": "1"},
        {"address": addr(2), "price_usd": "1", "coingecko_coin_id": "  "},
        {"address": addr(3), "price_usd": "1", "coingecko_coin_id": 123},
    ))
    assert all(rows[addr(i)]["coingecko_coin_id"] is None for i in (1, 2, 3))


def test_null_price_stays_null_and_zero_price_is_not_stored_as_zero():
    rows = md.parse_token_rows(payload(
        {"address": addr(1), "price_usd": None, "fdv_usd": None, "total_reserve_in_usd": "300"},
        {"address": addr(2), "price_usd": "0", "fdv_usd": "0", "total_reserve_in_usd": "0"},
    ))
    assert rows[addr(1)]["price_usd"] is None and rows[addr(1)]["liquidity_usd"] == 300.0
    assert rows[addr(2)]["price_usd"] is None          # 0 means "nothing in the pool"


def test_parse_skips_rows_without_an_address_and_tolerates_junk():
    assert md.parse_token_rows(payload({"symbol": "X"}, {"address": "  "})) == {}
    assert md.parse_token_rows({}) == {} and md.parse_token_rows(None) == {}
    assert md.parse_token_rows({"data": [{"attributes": None}, {}]}) == {}


# ------------------------------------------------------------------ targets

def test_collect_targets_filters_categories_uses_primary_contract_and_dedupes():
    rows = [
        {"id": "a", "category": "token", "contracts": [addr(1).upper().replace("X", "x"), addr(99)]},
        {"id": "b", "category": " Meme ", "contracts": [addr(2)]},
        {"id": "c", "category": "dex", "contracts": [addr(3)]},          # DeFi: not priced
        {"id": "d", "category": None, "contracts": [addr(4)]},
        {"id": "e", "category": "stablecoin", "contracts": []},          # nothing to look up
        {"id": "f", "category": "wrapped", "contracts": [addr(1)]},      # duplicate of a
        {"id": "g", "category": "institutional", "contracts": [addr(5)]},
    ]
    assert md.collect_targets(rows) == [addr(1), addr(2), addr(5)]


def test_priced_categories_match_token_and_stablecoin_segments():
    if not SEGMENTS.exists():
        pytest.skip("scoring/ not checked out next to ingestion/")
    spec = importlib.util.spec_from_file_location("segments_for_market_data_test", SEGMENTS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    expected = {c for c, seg in mod.SEGMENT_BY_CATEGORY.items() if seg in ("token", "stablecoin")}
    assert md.PRICED_CATEGORIES == expected


class _Query:
    def __init__(self, rows):
        self.rows, self.after, self.n = rows, None, None
    def select(self, *a): return self
    def gt(self, col, val): self.after = val; return self
    def order(self, *a): return self
    def limit(self, n): self.n = n; return self
    def execute(self):
        rows = [r for r in self.rows if self.after is None or r["id"] > self.after][: self.n]
        return type("R", (), {"data": rows})()


class _ReadClient:
    def __init__(self, rows): self.rows = rows
    def table(self, name):
        assert name == "projects"
        return _Query(self.rows)


def test_load_target_addresses_reads_past_the_1000_row_cap():
    rows = [{"id": f"p{i:05d}", "category": "token", "contracts": [addr(i)]} for i in range(2500)]
    assert len(md.load_target_addresses(_ReadClient(rows))) == 2500


# ------------------------------------------------------------------ refresh

class _WriteClient:
    def __init__(self): self.upserts = []
    def table(self, name):
        assert name == "token_market_data"
        outer = self
        class T:
            def upsert(self, rows, on_conflict=None):
                outer.upserts.append((list(rows), on_conflict))
                return self
            def execute(self): return None
        return T()


def _fetch_returning(prices):
    """fake fetch: returns a row (price from `prices`) for each requested address that has one."""
    calls = []
    def fetch(batch, key):
        calls.append((list(batch), key))
        return 200, payload(*({"address": a, "price_usd": str(prices[a]), "total_reserve_in_usd": "50000"}
                              for a in batch if a in prices))
    fetch.calls = calls
    return fetch


def test_refresh_batches_in_thirties_and_upserts_only_returned_tokens():
    addresses = [addr(i) for i in range(65)]
    prices = {a: 1.0 for a in addresses if int(a, 16) % 2 == 0}      # half have a pool
    fetch, client = _fetch_returning(prices), _WriteClient()
    s = md.refresh_market_data(client, addresses, "KEY", fetch=fetch)
    assert [len(c[0]) for c in fetch.calls] == [30, 30, 5]
    assert all(c[1] == "KEY" for c in fetch.calls)
    assert s["targets"] == 65 and s["batches"] == 3 and s["stopped"] is None
    written = [r["contract_address"] for rows, _ in client.upserts for r in rows]
    assert sorted(written) == sorted(prices) and s["upserted"] == len(prices)
    assert all(oc == "contract_address" for _, oc in client.upserts)
    assert all(r["fetched_at"] and r["source"] == "geckoterminal" for rows, _ in client.upserts for r in rows)


def test_extra_addresses_in_a_response_are_ignored():
    fetch = lambda batch, key: (200, payload({"address": addr(777), "price_usd": "9"}))
    client = _WriteClient()
    s = md.refresh_market_data(client, [addr(1)], "KEY", fetch=fetch)
    assert client.upserts == [] and s["upserted"] == 0


def test_rate_limit_stops_the_run_but_keeps_what_was_fetched():
    addresses = [addr(i) for i in range(90)]
    state = {"n": 0}
    def fetch(batch, key):
        state["n"] += 1
        if state["n"] == 2:
            return 429, None
        return 200, payload(*({"address": a, "price_usd": "1"} for a in batch))
    client = _WriteClient()
    s = md.refresh_market_data(client, addresses, "KEY", fetch=fetch)
    assert s["stopped"] == "rate_limited" and s["batches"] == 2 and s["upserted"] == 30


def test_a_failed_batch_is_skipped_and_the_run_continues():
    addresses = [addr(i) for i in range(60)]
    state = {"n": 0}
    def fetch(batch, key):
        state["n"] += 1
        if state["n"] == 1:
            return 0, None                      # network error
        return 200, payload(*({"address": a, "price_usd": "1"} for a in batch))
    s = md.refresh_market_data(_WriteClient(), addresses, "KEY", fetch=fetch)
    assert s["batches"] == 2 and s["upserted"] == 30 and s["stopped"] is None


def test_time_budget_stops_the_run():
    now = {"t": 0.0}
    def clock(): return now["t"]
    def fetch(batch, key):
        now["t"] += 100                         # each call "takes" 100s
        return 200, payload(*({"address": a, "price_usd": "1"} for a in batch))
    s = md.refresh_market_data(_WriteClient(), [addr(i) for i in range(120)], "KEY",
                               fetch=fetch, clock=clock, budget_seconds=150)
    assert s["stopped"] == "time_budget" and s["batches"] == 2


# ------------------------------------------------------------------ http + entry

def test_fetch_batch_uses_pro_endpoint_with_key_header(monkeypatch):
    seen = {}
    class Resp:
        status_code = 200
        def json(self): return {"data": []}
    def fake_get(url, headers=None, timeout=None):
        seen.update(url=url, headers=headers, timeout=timeout)
        return Resp()
    monkeypatch.setattr(md.requests, "get", fake_get)
    assert md.fetch_batch([addr(1), addr(2)], "KEY") == (200, {"data": []})
    assert seen["url"].startswith("https://pro-api.coingecko.com/api/v3/onchain/networks/arc/tokens/multi/")
    assert seen["url"].endswith(f"{addr(1)},{addr(2)}")
    assert seen["headers"]["x-cg-pro-api-key"] == "KEY" and seen["timeout"] == md.REQUEST_TIMEOUT_SECONDS


def test_fetch_batch_maps_failures_to_status_codes(monkeypatch):
    def boom(*a, **k): raise md.requests.ConnectionError("down")
    monkeypatch.setattr(md.requests, "get", boom)
    assert md.fetch_batch([addr(1)], "KEY") == (0, None)
    class Bad:
        status_code = 503
    monkeypatch.setattr(md.requests, "get", lambda *a, **k: Bad())
    assert md.fetch_batch([addr(1)], "KEY") == (503, None)
    class NotJson:
        status_code = 200
        def json(self): raise ValueError("no json")
    monkeypatch.setattr(md.requests, "get", lambda *a, **k: NotJson())
    assert md.fetch_batch([addr(1)], "KEY") == (200, None)


def test_run_skips_quietly_without_a_key(monkeypatch):
    monkeypatch.delenv("COINGECKO_PRO_API_KEY", raising=False)
    assert "skipped" in md.run_market_data_refresh()
