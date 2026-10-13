"""
main.py — FastAPI app entrypoint.

Isogram is a public data API (see docs/PRD.md, docs/AUDIT.md). Every route is
a read (GET) except three: POST /submit (rate-limited, only ever creates a
'pending' review row), POST /keys (rate-limited, only ever creates an API key row) and the
/admin/* routes (gated by X-Admin-Key). The
dashboard and badge embeds are thin clients of this API.

Run locally:
    uvicorn main:app --reload

Deploy: Railway/Render free tier (see docs/ARCHITECTURE.md §2.3).
"""

import logging
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from access import enforce_access
from db import get_client
from models import HealthResponse
from routes import badge, gas, keys, metrics, network, projects, scores, tvl, submit, admin, venues

log = logging.getLogger("isogram.main")


def _keep_snapshots_warm(interval: float) -> None:
    """Rebuild the /projects and /stats snapshots every `interval` seconds so a visitor arriving after a
    quiet spell never pays for a cold rebuild (cache.py). Off unless WARM_CACHE_SECONDS is set."""
    while True:
        try:
            client = get_client()
            projects.cached_project_summaries(client)
            network.cached_network_summary(client)
        except Exception:
            log.exception("cache warm-up failed; will retry")
        time.sleep(interval)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        interval = float(os.environ.get("WARM_CACHE_SECONDS", "0"))
    except ValueError:
        interval = 0.0
    if interval >= 30:
        threading.Thread(target=_keep_snapshots_warm, args=(interval,), name="cache-warm", daemon=True).start()
    yield


app = FastAPI(
    title="Isogram API",
    description="The data truth layer for Arc — USDC gas/flow, TVL, and Arc Native Score.",
    version="0.3.1",
    lifespan=lifespan,
    # Identifies every caller and applies the tiered per-minute limit (access.py).
    dependencies=[Depends(enforce_access)],
)

# CORS is deliberately wide open, not a dev-mode leftover: this is a public
# data API meant to be embedded/fetched from arbitrary frontends (dashboards,
# README badges, third-party tools) — see docs/PRD.md's "plug-and-play, not
# siloed" requirement. The two non-GET surfaces stay safe with open CORS:
# nothing authenticates via cookies (allow_credentials is off, and /admin
# needs an X-Admin-Key header a foreign site cannot know), and POST /submit
# is rate-limited and can only create a pending row for human review.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    # Lets browser code read the rate-limit headers (and back off on 429).
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Tier", "Retry-After"],
)

@app.middleware("http")
async def rate_limit_headers(request: Request, call_next):
    """Copy the headers access.enforce_access prepared onto the response, errors included."""
    response = await call_next(request)
    for name, value in getattr(request.state, "rate_headers", {}).items():
        response.headers.setdefault(name, value)
    return response


app.include_router(projects.router)
app.include_router(gas.router)
app.include_router(tvl.router)
app.include_router(scores.router)
app.include_router(badge.router)
app.include_router(network.router)
app.include_router(metrics.router)
app.include_router(submit.router)
app.include_router(admin.router)
app.include_router(keys.router)
app.include_router(keys.admin_router)
app.include_router(venues.router)


# HEAD is accepted so uptime monitors that probe with HEAD (the usual
# default) get a 200 instead of 405 and still wake the Render instance.
@app.api_route("/", methods=["GET", "HEAD"], response_model=HealthResponse)
def root():
    return {"status": "ok"}


@app.api_route("/health", methods=["GET", "HEAD"], response_model=HealthResponse)
def health():
    return {"status": "ok"}


