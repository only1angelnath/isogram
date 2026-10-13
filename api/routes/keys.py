"""
routes/keys.py - POST /keys (self-service API key), plus admin list/revoke.

Registration is deliberately light: a name for what you are building and an email so key holders can
be contacted about the API (changes, limits, abuse). The email is not verified, so it is a contact
point and not an identity. No password. The key is returned ONCE; only its hash is stored (apikeys.py).

Abuse controls: creation is limited per IP (5 / day), globally (100 / day) and per email (3 active
keys, KEY_MAX_PER_EMAIL), and every key
carries the same per-minute limit, so minting keys does not multiply anyone's quota per key beyond
what the creation limits already allow. A key can be revoked by an admin at any time.

Per docs/AUDIT.md this is a write route, but the only thing it can create is a row in api_keys;
that table has RLS on and no policies, so nothing else can read or alter it.
"""

import math
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

import access
import apikeys
from admin_auth import verify_admin_key
from db import get_write_client
from ratelimit import SlidingWindowLimiter, _int_env, client_ip

router = APIRouter(tags=["keys"])
admin_router = APIRouter(prefix="/admin/keys", tags=["admin"], dependencies=[Depends(verify_admin_key)])

DAY = 24 * 3600


def _build() -> tuple[SlidingWindowLimiter, SlidingWindowLimiter]:
    return (
        SlidingWindowLimiter(max(_int_env("KEY_CREATE_PER_IP", 5), 1), DAY),
        SlidingWindowLimiter(max(_int_env("KEY_CREATE_GLOBAL", 100), 1), DAY),
    )


create_per_ip, create_global = _build()


def reset_all() -> None:
    create_per_ip.reset()
    create_global.reset()


_EMAIL_RE = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@.]{2,}$")


class KeyRequest(BaseModel):
    name: str = Field(min_length=2, max_length=60, description="What you are building, e.g. 'Acme portfolio tracker'.")
    email: str = Field(max_length=254, description="Contact address for API changes, limits and abuse. Not verified, never shown publicly.")

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v):
        v = " ".join(v.split())  # collapses control characters and runs of whitespace
        if len(v) < 2:
            raise ValueError("name must be at least 2 characters")
        return v

    @field_validator("email")
    @classmethod
    def _clean_email(cls, v):
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("email must look like name@example.com")
        return v


class KeyCreated(BaseModel):
    api_key: str
    id: int
    name: str
    tier: str
    rate_limit_per_minute: int
    created_at: str
    note: str


@router.post("/keys", response_model=KeyCreated, status_code=201)
def create_key(body: KeyRequest, request: Request, response: Response, client=Depends(get_write_client)):
    """Create a free API key. It is shown once and cannot be recovered; keep it secret."""
    wait = create_per_ip.check(client_ip(request))
    scope = "from this address"
    if not wait:
        wait = create_global.check("*")
        scope = "across all clients"
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"Too many keys created {scope} today. Try again later.",
            headers={"Retry-After": str(math.ceil(wait))},
        )

    if apikeys.count_active_for_email(client, body.email) >= max(_int_env("KEY_MAX_PER_EMAIL", 3), 1):
        raise HTTPException(status_code=409, detail="This email already has the maximum number of active keys. Reuse one of them.")

    key = apikeys.generate_key()
    row = apikeys.insert_key(
        client,
        {"key_hash": apikeys.hash_key(key), "key_prefix": key[:8], "name": body.name, "email": body.email, "tier": "registered"},
    )
    if not row:
        raise HTTPException(status_code=500, detail="Key could not be created")
    response.headers["Cache-Control"] = "no-store"
    return {
        "api_key": key,
        "id": row["id"],
        "name": row["name"],
        "tier": row.get("tier") or "registered",
        "rate_limit_per_minute": int(row.get("rate_limit_per_minute") or access.default_limits()["registered"]),
        "created_at": row["created_at"],
        "note": "Store this key now. It is shown once and cannot be recovered. Send it as the X-API-Key header.",
    }


@admin_router.get("", response_model=list[dict])
def admin_list_keys(client=Depends(get_write_client)):
    """Every key (prefix only, never the key), newest last."""
    return apikeys.list_keys(client)


@admin_router.post("/{key_id}/revoke", response_model=dict)
def admin_revoke_key(key_id: int, client=Depends(get_write_client)):
    """Revoke a key. Takes effect immediately on this instance."""
    row = apikeys.revoke_key(client, key_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No active key with that id")
    apikeys.directory.clear()
    return {"id": row["id"], "revoked_at": row["revoked_at"]}
