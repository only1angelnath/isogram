"""
commands.py — argument parsing and Telegram message formatting, kept pure
(no network, no python-telegram-bot dependency) so it's directly unit-
testable, same pattern as scoring/compute_scores.py's build_*/compute_*
split.

Commands per docs/PRD.md §4:
    /score <project>
    /gas top10
    /tvl
"""

import re
from typing import Optional

DEFAULT_LEADERBOARD_LIMIT = 10
MAX_LEADERBOARD_LIMIT = 25

_TOPN_PATTERN = re.compile(r"^top(\d+)$", re.IGNORECASE)


def parse_leaderboard_limit(args: list[str]) -> int:
    """
    Parse a leaderboard command's arguments into a limit.
    Accepts: no args (default 10), "top10"/"TOP5" style, "top 10" (two
    tokens), or a bare number. Anything unparseable falls back to the
    default rather than erroring — a bot command should never crash on a
    typo'd argument. Clamped to MAX_LEADERBOARD_LIMIT to keep replies short.
    """
    if not args:
        return DEFAULT_LEADERBOARD_LIMIT

    joined = "".join(args).lower()  # handles both "top10" and "top 10"
    match = _TOPN_PATTERN.match(joined)
    if match:
        limit = int(match.group(1))
    elif args[0].isdigit():
        limit = int(args[0])
    else:
        return DEFAULT_LEADERBOARD_LIMIT

    if limit <= 0:
        return DEFAULT_LEADERBOARD_LIMIT
    return min(limit, MAX_LEADERBOARD_LIMIT)


def format_project_not_found(project_id: str) -> str:
    # No /projects command exists yet to point people at (bot/ only ships
    # /score, /gas, /tvl per docs/PRD.md §4) — keep this message generic
    # until one does, rather than referencing a command that doesn't exist.
    return f"No tracked project called '{project_id}'."


def format_api_error(project_id: Optional[str] = None) -> str:
    return "Isogram's API didn't respond — try again in a moment."


def format_score_reply(score_data: Optional[dict], project_id: str) -> str:
    """
    score_data is the JSON body from GET /scores/{project_id} (see
    api/models.py ProjectSummary) — score_data["score"] is None for a
    tracked project with no computed score yet (docs/BUGS.md #3), which is
    a different message than "not tracked at all".
    """
    if score_data is None:
        return format_project_not_found(project_id)

    name = score_data.get("name", project_id)
    score = score_data.get("score")
    if score is None:
        return f"*{name}* hasn't been scored yet — not enough data on Arc mainnet so far."

    tvl = score_data.get("tvl_usd")
    gas = score_data.get("usdc_gas_7d")
    users = score_data.get("unique_users_7d")

    lines = [f"*{name}* — Arc Native Score: `{score:.2f}`"]
    if tvl is not None:
        lines.append(f"TVL: ${tvl:,.2f}")
    if gas is not None:
        lines.append(f"USDC gas (7d): ${gas:,.4f}")
    if users is not None:
        lines.append(f"Unique users (7d): {users}")
    return "\n".join(lines)


def format_gas_leaderboard_reply(entries: list[dict]) -> str:
    """entries: JSON body from GET /gas/top (list of ProjectSummary)."""
    if not entries:
        return "No projects have USDC gas data yet — mainnet is still young."

    lines = ["*Top projects by USDC gas paid (7d)*"]
    for i, entry in enumerate(entries, start=1):
        name = entry.get("name", entry.get("id", "?"))
        gas = entry.get("usdc_gas_7d")
        lines.append(f"{i}. {name} — ${gas:,.4f}" if gas is not None else f"{i}. {name} — n/a")
    return "\n".join(lines)


def format_tvl_leaderboard_reply(entries: list[dict]) -> str:
    """entries: JSON body from GET /tvl/top (list of ProjectSummary)."""
    if not entries:
        return "No TVL data yet — mainnet is still young."

    lines = ["*Top projects by TVL*"]
    for i, entry in enumerate(entries, start=1):
        name = entry.get("name", entry.get("id", "?"))
        tvl = entry.get("tvl_usd")
        lines.append(f"{i}. {name} — ${tvl:,.2f}" if tvl is not None else f"{i}. {name} — n/a")
    return "\n".join(lines)


def format_tvl_reply(tvl_data: Optional[dict], project_id: str) -> str:
    if tvl_data is None:
        return format_project_not_found(project_id)

    name = tvl_data.get("name", project_id)
    tvl = tvl_data.get("tvl_usd")
    if tvl is None:
        return f"*{name}* has no TVL data yet."
    return f"*{name}* TVL: ${tvl:,.2f}"
