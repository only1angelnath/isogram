"""
routes/network.py — GET /stats

Network-wide totals (docs/BRANDING.md §5's honest stat strip). Read-only,
per docs/AUDIT.md. Deliberately no market cap — see
supabase/migrations/20260924080000_network_stats.sql.
"""

from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends

from aggregate import build_network_summary
from db import fetch_all_latest_scores, fetch_network_stats, fetch_projects, get_client
from cache import snapshots
from models import NetworkStats

router = APIRouter(tags=["stats"])


def load_network_summary(client):
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_projects = pool.submit(fetch_projects, client)
        f_scores = pool.submit(fetch_all_latest_scores, client)
        f_stats = pool.submit(fetch_network_stats, client)
        return build_network_summary(f_projects.result(), f_scores.result(), f_stats.result())


def cached_network_summary(client):
    """Snapshot of load_network_summary (see cache.py): at most a minute old."""
    return snapshots.get("stats", lambda: load_network_summary(client))


@router.get("/stats", response_model=NetworkStats)
def network_stats(client=Depends(get_client)):
    return cached_network_summary(client)
