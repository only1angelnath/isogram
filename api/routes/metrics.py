"""
routes/metrics.py - the time-series / breakdown metrics layer.

  GET /metrics/network/daily?days=30        chain-wide daily series
  GET /metrics/tokens/daily?days=30&token=  per-token daily transfers + volume
  GET /metrics/contracts/top?days=7&limit=  top contracts by USDC gas
  GET /projects/{id}/daily?days=30          one project's daily series
  GET /scores/{id}/history?limit=100        one project's score history

All read-only (docs/AUDIT.md). Backed by the rollups (docs/decisions/ADR-003).
Days the pipeline did not cover are ABSENT from the series, never zero-filled.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from aggregate import (
    TOKEN_SYMBOLS,
    build_network_daily,
    build_project_daily,
    build_score_history,
    build_token_daily,
    build_top_contracts,
)
from db import (
    TRACKED_TOKENS,
    fetch_network_daily,
    fetch_project,
    fetch_project_daily,
    fetch_score_history,
    fetch_token_daily,
    fetch_top_contracts,
    get_client,
)
from models import NetworkDay, ProjectDay, ScorePoint, TokenDay, TopContract

router = APIRouter(tags=["metrics"])


def _resolve_token(token: str | None) -> str | None:
    """Accept a symbol (USDC/EURC/USYC) or a tracked contract address."""
    if token is None:
        return None
    t = token.strip()
    if t.upper() in TRACKED_TOKENS:
        return TRACKED_TOKENS[t.upper()]
    if t.lower() in TOKEN_SYMBOLS:
        return t.lower()
    raise HTTPException(status_code=400, detail=f"Untracked token '{token}'. Tracked: {sorted(TRACKED_TOKENS)}")


@router.get("/metrics/network/daily", response_model=list[NetworkDay])
def network_daily(days: int = Query(30, ge=1, le=90), client=Depends(get_client)):
    """Chain-wide daily totals: transactions, failure rate, USDC gas (6-decimal view),
    contract deployments, blocks, token transfers, distinct active senders."""
    return build_network_daily(fetch_network_daily(client, days))


@router.get("/metrics/tokens/daily", response_model=list[TokenDay])
def tokens_daily(
    days: int = Query(30, ge=1, le=90),
    token: str | None = Query(None, description="USDC, EURC, USYC or a tracked token address"),
    client=Depends(get_client),
):
    """Daily transfer count and volume per tracked token (each in its own 6-decimal units).

    USDC: ALL USDC movement between holders - native sends and ERC-20 transfers - taken
    once from Arc's native system log and converted from 18 to 6 decimals at ingestion
    (docs/decisions/ADR-003). Gross movement: every transfer log counts, including
    intermediate hops through contracts such as routers. Mint/burn excluded.
    EURC / USYC: their ERC-20 Transfer logs. Volumes are never added across tokens.
    Rows before 2026-10-05 re-ingestion cutover may use the superseded ERC-20-only definition.
    """
    return build_token_daily(fetch_token_daily(client, days, _resolve_token(token)))


@router.get("/metrics/contracts/top", response_model=list[TopContract])
def contracts_top(
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(20, ge=1, le=100),
    client=Depends(get_client),
):
    """Top contracts by USDC gas over the window, with gas_share of all network gas
    and the owning project when one is tracked."""
    return build_top_contracts(fetch_top_contracts(client, days, limit))


@router.get("/projects/{project_id}/daily", response_model=list[ProjectDay])
def project_daily(project_id: str, days: int = Query(30, ge=1, le=90), client=Depends(get_client)):
    """One project's daily transactions, failures, USDC gas and unique senders."""
    if fetch_project(client, project_id) is None:
        raise HTTPException(status_code=404, detail=f"No tracked project '{project_id}'")
    return build_project_daily(fetch_project_daily(client, project_id, days))


@router.get("/scores/{project_id}/history", response_model=list[ScorePoint])
def score_history(project_id: str, limit: int = Query(100, ge=1, le=500), client=Depends(get_client)):
    """A project's Arc Native Score over time (one point per scoring run), newest first."""
    if fetch_project(client, project_id) is None:
        raise HTTPException(status_code=404, detail=f"No tracked project '{project_id}'")
    return build_score_history(fetch_score_history(client, project_id, limit))
