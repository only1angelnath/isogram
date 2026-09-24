"""
Tests for commands.py. Pure functions — no network, no Telegram — so these
run instantly and cover the actual user-facing text, same intent as
scoring/tests/test_scoring.py testing the formula in isolation from the DB.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from commands import (
    DEFAULT_LEADERBOARD_LIMIT,
    MAX_LEADERBOARD_LIMIT,
    format_api_error,
    format_gas_leaderboard_reply,
    format_project_not_found,
    format_score_reply,
    format_tvl_leaderboard_reply,
    format_tvl_reply,
    parse_leaderboard_limit,
)


# --- parse_leaderboard_limit ------------------------------------------------

def test_parse_leaderboard_limit_no_args_uses_default():
    assert parse_leaderboard_limit([]) == DEFAULT_LEADERBOARD_LIMIT


def test_parse_leaderboard_limit_topn_single_token():
    assert parse_leaderboard_limit(["top10"]) == 10
    assert parse_leaderboard_limit(["TOP5"]) == 5


def test_parse_leaderboard_limit_top_and_number_two_tokens():
    assert parse_leaderboard_limit(["top", "20"]) == 20


def test_parse_leaderboard_limit_bare_number():
    assert parse_leaderboard_limit(["7"]) == 7


def test_parse_leaderboard_limit_garbage_falls_back_to_default_not_error():
    assert parse_leaderboard_limit(["banana"]) == DEFAULT_LEADERBOARD_LIMIT


def test_parse_leaderboard_limit_zero_or_negative_falls_back_to_default():
    assert parse_leaderboard_limit(["top0"]) == DEFAULT_LEADERBOARD_LIMIT
    assert parse_leaderboard_limit(["-5"]) == DEFAULT_LEADERBOARD_LIMIT


def test_parse_leaderboard_limit_clamped_to_max():
    assert parse_leaderboard_limit(["top9999"]) == MAX_LEADERBOARD_LIMIT


# --- format_score_reply ------------------------------------------------------

def test_format_score_reply_not_found():
    reply = format_score_reply(None, "does-not-exist")
    assert "does-not-exist" in reply


def test_format_score_reply_unscored_project_is_not_zero():
    # Tracked but not yet scored — must read differently from "not tracked"
    # and must not claim a 0.00 score (docs/BUGS.md #3).
    data = {"id": "brand-new", "name": "Brand New", "score": None}
    reply = format_score_reply(data, "brand-new")
    assert "hasn't been scored yet" in reply
    assert "0.00" not in reply


def test_format_score_reply_with_full_data():
    data = {
        "name": "Isogram",
        "score": 0.8123,
        "tvl_usd": 1234.5,
        "usdc_gas_7d": 0.0042,
        "unique_users_7d": 7,
    }
    reply = format_score_reply(data, "isogram")
    assert "Isogram" in reply
    assert "0.81" in reply
    assert "1,234.50" in reply
    assert "7" in reply


def test_format_score_reply_partial_data_omits_missing_fields():
    data = {"name": "Partial", "score": 0.5, "tvl_usd": None, "usdc_gas_7d": None, "unique_users_7d": None}
    reply = format_score_reply(data, "partial")
    assert "TVL" not in reply
    assert "gas" not in reply.lower()


# --- leaderboards -------------------------------------------------------------

def test_format_gas_leaderboard_reply_empty():
    reply = format_gas_leaderboard_reply([])
    assert "No projects" in reply


def test_format_gas_leaderboard_reply_ranks_in_given_order():
    entries = [
        {"name": "A", "usdc_gas_7d": 10.0},
        {"name": "B", "usdc_gas_7d": 5.0},
    ]
    reply = format_gas_leaderboard_reply(entries)
    assert reply.index("1. A") < reply.index("2. B")


def test_format_tvl_leaderboard_reply_handles_null_tvl_entry():
    entries = [{"name": "A", "tvl_usd": None}]
    reply = format_tvl_leaderboard_reply(entries)
    assert "n/a" in reply


# --- /tvl <project> -----------------------------------------------------------

def test_format_tvl_reply_not_found():
    reply = format_tvl_reply(None, "nope")
    assert "nope" in reply


def test_format_tvl_reply_no_data_yet():
    reply = format_tvl_reply({"name": "Quiet", "tvl_usd": None}, "quiet")
    assert "no TVL data" in reply


def test_format_tvl_reply_with_data():
    reply = format_tvl_reply({"name": "Isogram", "tvl_usd": 42.5}, "isogram")
    assert "42.50" in reply


# --- misc ----------------------------------------------------------------------

def test_format_project_not_found_includes_id():
    assert "myproj" in format_project_not_found("myproj")


def test_format_api_error_is_non_empty_string():
    assert isinstance(format_api_error(), str)
    assert len(format_api_error()) > 0
