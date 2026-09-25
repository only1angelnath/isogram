"""
admin_auth.py — gates every /admin/* route behind a shared secret.

This is deliberately simple (one static key, one header check) rather than
real user accounts/sessions — matches the project's scale right now (a
small team, not a multi-admin product with audit trails per-user). If the
team grows past "everyone shares one admin password," swap this for real
auth; nothing downstream (routes/admin.py) needs to change, it just calls
verify_admin_key as a dependency.
"""

import hmac
import os

from fastapi import Header, HTTPException


def verify_admin_key(x_admin_key: str = Header(default="")) -> None:
    expected = os.environ.get("ADMIN_API_KEY")
    if not expected:
        # Fail closed: if the secret was never configured, admin routes
        # are unreachable rather than silently open.
        raise HTTPException(status_code=503, detail="Admin routes not configured")
    if not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing admin key")
