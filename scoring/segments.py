"""
segments.py - which kind of project is this, and therefore how is it measured?

MUST stay identical to api/aggregate.py::SEGMENT_BY_CATEGORY (scoring and the API are
separate deployables, so the table is duplicated; tests/test_segments_sync.py fails if
they drift). See docs/decisions/ADR-004-score-only-defi-peers.md.

Only the "defi" segment is scored and has TVL computed: a composite of gas, users, TVL and
age is meaningful between comparable DeFi protocols, and meaningless between a router and a
memecoin (the old version min-max normalised every project against every other one).
"""

SEGMENT_BY_CATEGORY = {
    "dex": "defi", "lending": "defi", "yield": "defi", "liquid-staking": "defi",
    "launchpad": "launchpad",
    "infra": "infra", "bridge": "infra", "oracle": "infra", "governance": "infra",
    "stablecoin": "stablecoin", "institutional": "stablecoin",
    "token": "token", "meme": "token", "wrapped": "token",
}

SCORED_SEGMENTS = {"defi"}   # get a composite score, normalised within this peer group only
TVL_SEGMENTS = {"defi"}      # TVL (value locked in the contract) is only meaningful here


def segment_for(category):
    return SEGMENT_BY_CATEGORY.get((category or "").strip().lower(), "other")
