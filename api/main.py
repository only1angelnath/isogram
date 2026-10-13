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

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from access import enforce_access
from models import HealthResponse
from routes import badge, gas, keys, metrics, network, projects, scores, tvl, submit, admin, venues

app = FastAPI(
    title="Isogram API",
    description="The data truth layer for Arc — USDC gas/flow, TVL, and Arc Native Score.",
    version="0.3.0",
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


