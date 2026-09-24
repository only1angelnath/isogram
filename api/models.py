"""
models.py — Pydantic response schemas for the API.

These mirror aggregate.py's output dicts field-for-field; FastAPI validates
and documents (via /docs) against these automatically.
"""

from typing import Optional

from pydantic import BaseModel


class ProjectSummary(BaseModel):
    id: str
    name: str
    category: Optional[str] = None
    score: Optional[float] = None
    tvl_usd: Optional[float] = None
    usdc_gas_7d: Optional[float] = None
    unique_users_7d: Optional[int] = None
    computed_at: Optional[str] = None


class ProjectDetail(ProjectSummary):
    contracts: list[str] = []
    created_at: Optional[str] = None


class HealthResponse(BaseModel):
    status: str


class NetworkStats(BaseModel):
    """
    Network-wide totals for the dashboard's stat strip (docs/BRANDING.md
    §5). Deliberately excludes market cap — see
    supabase/migrations/20260924080000_network_stats.sql's comment on why
    that's a separate, not-yet-built feature (needs a price oracle + supply
    tracking, and doesn't mean much for the currently-tracked stablecoins
    and Uniswap v4, which has no token on Arc).
    """

    total_projects: int
    total_scored: int
    total_tvl_usd: Optional[float] = None
    total_volume_7d: Optional[float] = None
    total_tx_7d: Optional[int] = None
    total_unique_users_7d: Optional[int] = None
    computed_at: Optional[str] = None
