"""
main.py — FastAPI app entrypoint.

Isogram is a public, read-only data API (see docs/PRD.md, docs/AUDIT.md) —
every route here is a GET. Dashboard, Telegram bot, and badge embeds are all
thin clients of this API (docs/ARCHITECTURE.md §3).

Run locally:
    uvicorn main:app --reload

Deploy: Railway/Render free tier (see docs/ARCHITECTURE.md §2.3).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from models import HealthResponse
from routes import badge, gas, projects, scores, tvl

app = FastAPI(
    title="Isogram API",
    description="The data truth layer for Arc — USDC gas/flow, TVL, and Arc Native Score.",
    version="0.1.0",
)

# CORS is deliberately wide open, not a dev-mode leftover: this is a public
# read-only data API meant to be embedded/fetched from arbitrary frontends
# (dashboards, README badges, third-party tools) — see docs/PRD.md's
# "plug-and-play, not siloed" requirement. Every route is GET-only with no
# write capability (docs/AUDIT.md), so an open CORS policy carries none of
# the risk it would on an API that accepts writes.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(gas.router)
app.include_router(tvl.router)
app.include_router(scores.router)
app.include_router(badge.router)


@app.get("/", response_model=HealthResponse)
def root():
    return {"status": "ok"}


@app.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok"}
