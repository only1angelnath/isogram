"""
Tests for the pure logic in db.py. Network-dependent functions (get_client,
upserts, etc.) aren't unit-tested here — they're exercised by the manual
end-to-end check in docs/TESTING.md. This file covers build_contract_project_map
and resolve_project_id, which don't need a live database.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import build_contract_project_map, resolve_project_id


def test_build_contract_project_map_basic():
    rows = [
        {"id": "usdc", "contracts": ["0xAAA1111111111111111111111111111111111"]},
        {"id": "uniswap-v4", "contracts": ["0xBBB2222222222222222222222222222222222"]},
    ]
    result = build_contract_project_map(rows)
    assert result["0xaaa1111111111111111111111111111111111"] == "usdc"
    assert result["0xbbb2222222222222222222222222222222222"] == "uniswap-v4"


def test_build_contract_project_map_lowercases_addresses():
    rows = [{"id": "usdc", "contracts": ["0xABCDEF0000000000000000000000000000ABCD"]}]
    result = build_contract_project_map(rows)
    assert "0xabcdef0000000000000000000000000000abcd" in result
    assert "0xABCDEF0000000000000000000000000000ABCD" not in result


def test_build_contract_project_map_handles_multiple_contracts_per_project():
    rows = [{"id": "multi", "contracts": ["0x1111111111111111111111111111111111111", "0x2222222222222222222222222222222222222"]}]
    result = build_contract_project_map(rows)
    assert result["0x1111111111111111111111111111111111111"] == "multi"
    assert result["0x2222222222222222222222222222222222222"] == "multi"


def test_build_contract_project_map_handles_empty_contracts_list():
    rows = [{"id": "no-contracts", "contracts": []}]
    result = build_contract_project_map(rows)
    assert result == {}


def test_build_contract_project_map_handles_missing_contracts_key():
    rows = [{"id": "malformed"}]
    result = build_contract_project_map(rows)
    assert result == {}


def test_build_contract_project_map_handles_empty_input():
    assert build_contract_project_map([]) == {}


def test_resolve_project_id_found():
    lookup = {"0xaaa": "usdc"}
    assert resolve_project_id("0xAAA", lookup) == "usdc"


def test_resolve_project_id_not_found_returns_none():
    lookup = {"0xaaa": "usdc"}
    assert resolve_project_id("0xzzz", lookup) is None


def test_resolve_project_id_case_insensitive():
    lookup = {"0xabc123": "some-project"}
    assert resolve_project_id("0xABC123", lookup) == "some-project"
