"""
api_client.py — thin HTTP client over the Isogram FastAPI.

Per docs/PRD.md §4 and docs/ARCHITECTURE.md §2.6, the bot is a client of the
API, not a second copy of the query/DB logic — it never touches Postgres.
Every function here just calls a route already built in api/routes/ and
returns the parsed JSON (or raises ApiError). Message formatting lives in
commands.py, kept separate so it's testable without any network calls.
"""

import asyncio
import os
from typing import Optional

import httpx

DEFAULT_TIMEOUT_SECONDS = 30
# 30s, not 10s: Render's free-tier web services (the API) spin down after
# ~15 minutes idle and can take 20-30s to wake back up on the next request.
# A short timeout here would misreport a cold start as a real API outage.

# Render's free tier returns 502 Bad Gateway WHILE the container is still
# booting from a cold start (not a slow-but-eventually-correct response) —
# confirmed in production: the exact same request that 502'd immediately
# succeeded a few seconds later once the container finished waking up. A
# short retry-with-backoff rides out that window automatically so the user
# never sees it, instead of failing on the first try and telling them to
# retry manually.
COLD_START_RETRY_DELAYS_SECONDS = [2, 5, 10]


class ApiError(Exception):
    """Raised for any non-2xx response or network failure talking to the API."""


def get_api_base_url() -> str:
    url = os.environ.get("ISOGRAM_API_BASE_URL")
    if not url:
        raise RuntimeError("ISOGRAM_API_BASE_URL must be set (see .env.example).")
    return url.rstrip("/")


async def _get_json(client: httpx.AsyncClient, path: str) -> dict:
    last_error: Optional[str] = None

    for attempt, delay_before in enumerate([0] + COLD_START_RETRY_DELAYS_SECONDS):
        if delay_before:
            await asyncio.sleep(delay_before)

        try:
            resp = await client.get(path, timeout=DEFAULT_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            raise ApiError(f"Could not reach the Isogram API: {exc}") from exc

        if resp.status_code == 404:
            return None
        if resp.status_code in (502, 503):
            # Cold-start signature (see COLD_START_RETRY_DELAYS_SECONDS) —
            # worth another try, not an immediate failure.
            last_error = f"{resp.status_code} for {path}"
            continue
        if resp.status_code >= 400:
            raise ApiError(f"Isogram API returned {resp.status_code} for {path}")
        return resp.json()

    raise ApiError(
        f"Isogram API still returning {last_error} after retrying — "
        "likely still cold-starting; try again shortly."
    )


async def get_project(client: httpx.AsyncClient, project_id: str) -> Optional[dict]:
    """GET /projects/{project_id}. Returns None if the project isn't tracked."""
    return await _get_json(client, f"/projects/{project_id}")


async def get_score(client: httpx.AsyncClient, project_id: str) -> Optional[dict]:
    """GET /scores/{project_id}. Returns None if the project isn't tracked."""
    return await _get_json(client, f"/scores/{project_id}")


async def get_gas_top(client: httpx.AsyncClient, limit: int) -> list[dict]:
    """GET /gas/top?limit=N."""
    result = await _get_json(client, f"/gas/top?limit={limit}")
    return result or []


async def get_tvl_top(client: httpx.AsyncClient, limit: int) -> list[dict]:
    """GET /tvl/top?limit=N."""
    result = await _get_json(client, f"/tvl/top?limit={limit}")
    return result or []


async def get_tvl(client: httpx.AsyncClient, project_id: str) -> Optional[dict]:
    """GET /tvl/{project_id}. Returns None if the project isn't tracked."""
    return await _get_json(client, f"/tvl/{project_id}")