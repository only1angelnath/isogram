"""
scoring.py — the Arc Native Score formula (v1), pure functions only.

Formula, per docs/SCHEMA.md (do not change the shape of this without an ADR —
see AGENTS.md rule 5 and docs/decisions/ADR-002-scoring-formula.md):

    score = w1 * normalize(usdc_gas_7d)
          + w2 * normalize(unique_users_7d)
          + w3 * normalize(tvl_usd)
          + w4 * contract_age_bonus

v1 weights are equal (0.25 each) per docs/SCHEMA.md. `normalize()` is a
min-max scale within the current set of tracked projects, so the score is
always relative to what's actually live on Arc right now rather than an
absolute threshold that means nothing on a two-week-old chain.

Two formula details were left unspecified in docs/SCHEMA.md and are pinned
down here for the first time — see docs/decisions/ADR-002-scoring-formula.md
for the record of these decisions:
  - unique_users_7d's data source (gas_events has no sender column; it's
    derived from token_flows.from_address instead — see ADR-002)
  - contract_age_bonus's curve shape (linear ramp to a cap, see below)

Graceful degradation (docs/BUGS.md #3): with 0 or 1 tracked projects, or any
metric where every project ties, there is no relative signal to extract.
normalize() returns 0.0 in that case rather than fabricating a mid-ranking
value — a real signal will separate projects once more data exists.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

WEIGHT_GAS = Decimal("0.25")
WEIGHT_USERS = Decimal("0.25")
WEIGHT_TVL = Decimal("0.25")
WEIGHT_AGE = Decimal("0.25")

# contract_age_bonus reaches its full value (1.0) at this many days old, and
# ramps linearly from 0 before that. 30 days is a v1 starting point, not a
# permanent constant — see ADR-002 for the reasoning and how to revisit it.
AGE_BONUS_CAP_DAYS = 30


def normalize(value: Decimal, all_values: Iterable[Decimal]) -> Decimal:
    """
    Min-max scale `value` to [0, 1] relative to `all_values` (which must
    include `value` itself). Returns Decimal("0") if all_values is empty or
    every value ties (max == min) — there is no relative signal to encode,
    so this contributes nothing to the score rather than an arbitrary
    mid-point (see module docstring).
    """
    values = list(all_values)
    if not values:
        return Decimal("0")
    lo, hi = min(values), max(values)
    if hi == lo:
        return Decimal("0")
    return (value - lo) / (hi - lo)


def contract_age_bonus(created_at: datetime, now: datetime) -> Decimal:
    """
    Linear ramp from 0 (just deployed) to 1 (>= AGE_BONUS_CAP_DAYS old).
    Clamped to [0, 1] so a clock-skew or malformed created_at never produces
    a bonus outside that range.
    """
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age_days = (now - created_at).total_seconds() / 86400
    ratio = Decimal(str(age_days)) / Decimal(AGE_BONUS_CAP_DAYS)
    if ratio < 0:
        return Decimal("0")
    if ratio > 1:
        return Decimal("1")
    return ratio


def compute_score(
    usdc_gas_7d: Decimal,
    all_usdc_gas_7d: Iterable[Decimal],
    unique_users_7d: Decimal,
    all_unique_users_7d: Iterable[Decimal],
    tvl_usd: Decimal,
    all_tvl_usd: Iterable[Decimal],
    age_bonus: Decimal,
) -> Decimal:
    """
    Combine the four normalized components with v1's equal weights. Each
    `all_*` iterable is the corresponding raw metric across every currently
    tracked project (including this one), used only to compute the min-max
    range for that metric's normalize() call.
    """
    return (
        WEIGHT_GAS * normalize(usdc_gas_7d, all_usdc_gas_7d)
        + WEIGHT_USERS * normalize(unique_users_7d, all_unique_users_7d)
        + WEIGHT_TVL * normalize(tvl_usd, all_tvl_usd)
        + WEIGHT_AGE * age_bonus
    )
