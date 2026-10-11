"""
routes/venues.py - GET /venues

Per-venue (DEX / launch platform) 24h volume on Arc from GeckoTerminal's top pools; third-party data,
refreshed hourly by the ingestion worker (ingestion/venues.py). Read-only. If the table is unreachable
the answer is 503, not an empty list that would look like "no trading on Arc".
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from aggregate import build_venues
from db import fetch_venues, get_client
from models import VenueSummary

router = APIRouter(prefix="/venues", tags=["venues"])
log = logging.getLogger("isogram.venues")


@router.get("", response_model=list[VenueSummary])
def list_venues(kind: Optional[str] = Query(None, pattern="^(dex|launchpad)$"), client=Depends(get_client)):
    """Venues with 24h volume, biggest first. `share` is always relative to ALL venues, even when filtered by kind."""
    try:
        rows = fetch_venues(client)
    except Exception:
        log.exception("venue data unavailable")
        raise HTTPException(status_code=503, detail="Venue data is temporarily unavailable.")
    venues = build_venues(rows)
    return [v for v in venues if kind is None or v["kind"] == kind]
