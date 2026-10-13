"""
access.py - who is calling, and how much they may call.

One FastAPI dependency (enforce_access) is attached to the whole app. It identifies the caller and
applies a per-minute sliding-window limit:

  tier         identified by              default limit      bucket
  anonymous    no key                     60 / min           client IP
  badge        no key, GET /badge/*       300 / min          client IP   (README badges load in bursts)
  registered   X-API-Key: isg_...         600 / min          the key
  internal     X-API-Key in INTERNAL_API_KEYS  6000 / min     the key     (the dashboard's server)

An unknown or revoked key is a 401, never a silent downgrade to anonymous, so a typo is noticed.
If the key database is unreachable the request is served as anonymous instead (logged), so an outage
of the key table does not take the API down.

Unknown keys are not cached forever, so random key strings could otherwise be used to make the API hit
its database. A separate small budget (30 / min per IP) is charged for every key lookup that misses the
cache, which bounds that.

/admin/* is gated by X-Admin-Key; it gets its own per-IP limit (30 / min) so that key cannot be guessed
at speed. / and /health are exempt so uptime monitors never get throttled.

Every response (errors included, via main.py's middleware) carries X-RateLimit-Limit, X-RateLimit-Remaining and X-RateLimit-Tier; a 429 adds Retry-After.
Limits are per process (the API is one Render instance); see ratelimit.py for why that is enough, and
for how the client IP is read behind Render's proxies (TRUSTED_PROXY_HOPS).

Env (all optional): ANON_LIMIT_PER_MIN, BADGE_LIMIT_PER_MIN, KEY_LIMIT_PER_MIN, INTERNAL_LIMIT_PER_MIN,
ADMIN_LIMIT_PER_MIN, LOOKUP_LIMIT_PER_MIN, INTERNAL_API_KEYS.
"""

import logging
import math
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, Request

import apikeys
from db import get_write_client
from ratelimit import SlidingWindowLimiter, _int_env, client_ip

log = logging.getLogger("isogram.access")

WINDOW_SECONDS = 60
EXEMPT_PATHS = {"/", "/health"}


def default_limits() -> dict[str, int]:
    return {
        "anonymous": max(_int_env("ANON_LIMIT_PER_MIN", 60), 1),
        "badge": max(_int_env("BADGE_LIMIT_PER_MIN", 300), 1),
        "registered": max(_int_env("KEY_LIMIT_PER_MIN", 600), 1),
        "internal": max(_int_env("INTERNAL_LIMIT_PER_MIN", 6000), 1),
        "admin": max(_int_env("ADMIN_LIMIT_PER_MIN", 30), 1),
        "lookup": max(_int_env("LOOKUP_LIMIT_PER_MIN", 30), 1),
    }


class CountingLimiter(SlidingWindowLimiter):
    """SlidingWindowLimiter that can also report how many hits remain in the window."""

    def remaining(self, key: str) -> int:
        with self._lock:
            return max(self.limit - len(self._hits.get(key, ())), 0)


_limiters: dict[tuple[str, int], CountingLimiter] = {}


def limiter_for(name: str, limit: int) -> CountingLimiter:
    """One limiter per (tier, limit) pair, so a key with a custom limit gets its own window length of 60 s."""
    k = (name, limit)
    lim = _limiters.get(k)
    if lim is None:
        lim = _limiters[k] = CountingLimiter(limit, WINDOW_SECONDS)
    return lim


def reset_all() -> None:
    """Forget every counter and cached key (used by tests)."""
    _limiters.clear()
    apikeys.directory.clear()


@dataclass
class Principal:
    tier: str
    bucket: str
    limit: int


def _retry_headers(limit: int, remaining: int, tier: str, wait: float = 0.0) -> dict[str, str]:
    h = {"X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": str(remaining), "X-RateLimit-Tier": tier}
    if wait:
        h["Retry-After"] = str(math.ceil(wait))
    return h


def _too_many(limit: int, tier: str, wait: float, what: str) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=f"Rate limit exceeded ({limit} requests per minute for {what}). Retry in {math.ceil(wait)} s. "
               f"Register a free API key for a higher limit: see /docs on the dashboard.",
        headers=_retry_headers(limit, 0, tier, wait),
    )


def _identify_key(key: str, ip: str, limits: dict[str, int]) -> Principal:
    """Resolve an X-API-Key value to a Principal, or raise 401 / 429."""
    if apikeys.match_internal(key):
        return Principal("internal", f"internal:{apikeys.hash_key(key)[:12]}", limits["internal"])
    if not apikeys.looks_like_key(key):
        raise HTTPException(status_code=401, detail="Invalid API key", headers={"WWW-Authenticate": "ApiKey"})

    key_hash = apikeys.hash_key(key)
    hit, record = apikeys.directory.cached(key_hash)
    if not hit:
        wait = limiter_for("lookup", limits["lookup"]).check(ip)
        if wait:
            raise _too_many(limits["lookup"], "anonymous", wait, "API key lookups from this address")
        try:
            record = apikeys.fetch_key_by_hash(get_write_client(), key_hash)
        except Exception:
            log.exception("api key lookup failed; serving this request as anonymous")
            return Principal("anonymous", f"ip:{ip}", limits["anonymous"])
        apikeys.directory.store(key_hash, record)
        if record and not record.get("revoked_at"):
            _maybe_touch(record)

    if record is None or record.get("revoked_at"):
        raise HTTPException(status_code=401, detail="Invalid or revoked API key", headers={"WWW-Authenticate": "ApiKey"})
    limit = record.get("rate_limit_per_minute") or limits["registered"]
    return Principal(record.get("tier") or "registered", f"key:{record['id']}", int(limit))


def _maybe_touch(record: dict) -> None:
    """Best effort 'last used' stamp, at most about once an hour per key (it piggybacks on cache misses)."""
    from datetime import datetime, timezone

    last = record.get("last_used_at")
    if last:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds()
            if age < apikeys.TOUCH_INTERVAL_SECONDS:
                return
        except ValueError:
            pass
    try:
        apikeys.touch_key(get_write_client(), record["id"])
    except Exception:
        log.exception("could not stamp last_used_at for key %s", record.get("id"))


def enforce_access(request: Request, x_api_key: Optional[str] = Header(default=None)) -> None:
    """App-wide dependency: identify the caller, count the request, set rate-limit headers."""
    path = request.url.path
    if request.method == "OPTIONS" or path in EXEMPT_PATHS:
        return
    limits = default_limits()
    ip = client_ip(request)

    if path == "/admin" or path.startswith("/admin/"):
        lim = limits["admin"]
        wait = limiter_for("admin", lim).check(ip)
        if wait:
            raise _too_many(lim, "admin", wait, "admin routes")
        return

    key = (x_api_key or "").strip()
    if key:
        principal = _identify_key(key, ip, limits)
    elif path.startswith("/badge/"):
        principal = Principal("badge", f"ip:{ip}", limits["badge"])
    else:
        principal = Principal("anonymous", f"ip:{ip}", limits["anonymous"])

    lim = limiter_for(principal.tier if principal.tier in ("anonymous", "badge", "internal") else "key", principal.limit)
    wait = lim.check(principal.bucket)
    if wait:
        raise _too_many(principal.limit, principal.tier, wait, "this " + ("key" if principal.bucket.startswith("key:") else "address"))
    # Stored on the request and copied onto the response by main.py's middleware, so the headers also appear
    # on error responses (a 404 still counts against the limit and the caller should see that).
    request.state.rate_headers = _retry_headers(principal.limit, lim.remaining(principal.bucket), principal.tier)
