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
