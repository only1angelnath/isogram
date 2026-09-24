"""
routes/network.py — GET /stats

Network-wide totals (docs/BRANDING.md §5's honest stat strip). Read-only,
per docs/AUDIT.md. Deliberately no market cap — see
supabase/migrations/20260924080000_network_stats.sql.
"""

from fastapi import APIRouter, Depends

from aggregate import build_network_summary
from db import fetch_all_latest_scores, fetch_network_stats, fetch_projects, get_client
from models import NetworkStats

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=NetworkStats)
def network_stats(client=Depends(get_client)):
    projects = fetch_projects(client)
    scores = fetch_all_latest_scores(client)
    network_stats_row = fetch_network_stats(client)
    return build_network_summary(projects, scores, network_stats_row)
