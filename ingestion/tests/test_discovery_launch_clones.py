"""Launchpad clone tokens are TOKENS (never 'launchpad', never a hand-verified special category)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def dc(monkeypatch):
    """discovery.py reads Supabase settings at import time. Provide throwaway values for the
    import only (monkeypatch restores the environment), so no other test sees them."""
    monkeypatch.setenv("SUPABASE_URL", "http://localhost")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    import discovery
    return discovery


def info(token_name, symbol, impl="ArgusV4LaunchToken7"):
    return {"is_verified": True, "name": None, "token": {"name": token_name, "symbol": symbol},
            "implementations": [{"name": impl}] if impl else []}


def test_launch_clone_is_a_plain_token_not_a_launchpad(dc):
    r = dc._classify_from_blockscout(info("Cat Coin", "CAT"))
    assert r["category"] == "token"


def test_clone_named_like_a_stablecoin_cannot_enter_a_curated_segment(dc):
    for name, sym in (("USDC", "USDC"), ("Wrapped Ether", "WETH"), ("Circle USD", "USDX")):
        assert dc._classify_from_blockscout(info(name, sym))["category"] == "token"


def test_implementation_match_is_case_insensitive(dc):
    assert dc._classify_from_blockscout(info("X", "X", impl="somethingLAUNCHsomething"))["category"] == "token"


def test_ordinary_token_without_a_clone_implementation_is_still_inferred(dc):
    r = dc._classify_from_blockscout(info("Arc Dog", "ADOG", impl=None))
    assert r["category"] == dc._infer_category("Arc Dog", "ADOG")
    assert r["category"] != "launchpad"


def test_nothing_in_classification_can_produce_launchpad_anymore(dc):
    for token in ({"name": "Launchpad Token", "symbol": "LPAD"}, {"name": "Launch", "symbol": "LAUNCH"}):
        out = dc._classify_from_blockscout({"is_verified": True, "token": token, "implementations": []})
        assert out["category"] != "launchpad"
