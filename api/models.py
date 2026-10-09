"""
models.py — Pydantic response schemas for the API.

These mirror aggregate.py's output dicts field-for-field; FastAPI validates
and documents (via /docs) against these automatically.
"""

from typing import Optional

from pydantic import BaseModel, field_validator


class MarketData(BaseModel):
    """Third-party market data (GeckoTerminal) for a token or stablecoin project. NOT chain-derived.

    quality: "ok" (enough liquidity and trading to trust the price), "thin" (little liquidity),
    "inactive" (reserves but almost no trading, so the price may be stale or spoofed).
    FDV and market cap are only given when quality is "ok"; they are not meaningful otherwise.
    """

    price_usd: Optional[float] = None
    fdv_usd: Optional[float] = None
    market_cap_usd: Optional[float] = None
    liquidity_usd: Optional[float] = None
    volume_24h_usd: Optional[float] = None
    quality: str
    listed_on_coingecko: bool = False
    source: str
    fetched_at: str


class ProjectSummary(BaseModel):
    id: str
    name: str
    category: Optional[str] = None
    # defi | launchpad | infra | token | stablecoin | other - decides which metrics apply
    segment: Optional[str] = None
    tier: Optional[str] = None  # "curated" (hand-seeded) | "discovered" (auto-promoted)
    score: Optional[float] = None
    tvl_usd: Optional[float] = None
    usdc_gas_7d: Optional[float] = None
    unique_users_7d: Optional[int] = None
    tx_count_7d: Optional[int] = None
    failed_tx_7d: Optional[int] = None
    failed_rate_7d: Optional[float] = None
    computed_at: Optional[str] = None
    # Token / stablecoin projects only, and only while the data is fresh (see aggregate.build_market).
    market: Optional[MarketData] = None


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



class NetworkDay(BaseModel):
    day: str
    tx_count: Optional[int] = None
    failed_tx_count: Optional[int] = None
    failed_rate: Optional[float] = None
    usdc_gas_paid: Optional[float] = None
    avg_gas_per_tx_usdc: Optional[float] = None
    contract_creations: Optional[int] = None
    blocks: Optional[int] = None
    token_transfer_count: Optional[int] = None
    active_addresses: Optional[int] = None
    source: Optional[str] = None
    partial: bool = False


class TokenDay(BaseModel):
    day: str
    token_address: str
    symbol: Optional[str] = None
    transfer_count: Optional[int] = None
    volume: Optional[float] = None
    avg_transfer_size: Optional[float] = None


class TopContract(BaseModel):
    contract_address: str
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    category: Optional[str] = None
    tx_count: Optional[int] = None
    failed_tx_count: Optional[int] = None
    failed_rate: Optional[float] = None
    usdc_gas: Optional[float] = None
    gas_share: Optional[float] = None


class ProjectDay(BaseModel):
    day: str
    tx_count: Optional[int] = None
    failed_tx_count: Optional[int] = None
    failed_rate: Optional[float] = None
    usdc_gas: Optional[float] = None
    unique_users: Optional[int] = None


class ScorePoint(BaseModel):
    computed_at: str
    score: Optional[float] = None
    tvl_usd: Optional[float] = None
    usdc_gas_7d: Optional[float] = None
    unique_users_7d: Optional[int] = None


class PipelineStatus(BaseModel):
    status: str  # "live" | "behind" | "unknown"
    last_block_number: Optional[int] = None
    data_through: Optional[str] = None  # timestamp of the last block applied
    lag_seconds: Optional[int] = None
    checkpoint_updated_at: Optional[str] = None

