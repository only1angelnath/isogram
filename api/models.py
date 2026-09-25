"""
models.py — Pydantic response schemas for the API.

These mirror aggregate.py's output dicts field-for-field; FastAPI validates
and documents (via /docs) against these automatically.
"""

from typing import Optional

from pydantic import BaseModel, field_validator


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
    avg_score: Optional[float] = None
    total_volume_7d: Optional[float] = None
    total_tx_7d: Optional[int] = None
    total_unique_users_7d: Optional[int] = None
    computed_at: Optional[str] = None

class SubmissionRequest(BaseModel):
    """POST /submit body — a project owner proposing their project for
    listing. Every field but contract_address is optional; classification
    still runs normally on review, this is just a head start / signal."""

    contract_address: str
    proposed_name: Optional[str] = None
    proposed_category: Optional[str] = None
    socials: Optional[dict] = None
    submitter_contact: Optional[str] = None
    note: Optional[str] = None


class SubmissionResponse(BaseModel):
    id: int
    contract_address: str
    status: str
    created_at: str

class AdminClassifyRequest(BaseModel):
    contract_address: str
    category: str
    name: Optional[str] = None


class AdminReviewRequest(BaseModel):
    decision: str  # 'approve' or 'reject'
    category: Optional[str] = None
    name: Optional[str] = None
    note: Optional[str] = None

    @field_validator("decision")
    @classmethod
    def _decision_valid(cls, v):
        if v not in ("approve", "reject"):
            raise ValueError("decision must be 'approve' or 'reject'")
        return v

