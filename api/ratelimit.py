"""
ratelimit.py — small in-memory sliding-window rate limiter for POST /submit.

Why in-memory is enough here: the API runs as ONE Render instance, so a
process-local counter sees every request. If this ever scales to several
instances, each would count separately — swap the store for Redis/Postgres
then; callers only use limit_submissions(), so nothing else changes.

Two layers:
  - per client IP  (default 5 / hour): stops one person flooding the queue
  - global         (default 100 / hour): backstop if someone rotates IPs

Rejected requests are NOT recorded, so waiting out the window really does
free the slot, and a blocked client cannot burn the shared global budget.

Client IP: X-Forwarded-For is client-controlled at its LEFT end (a caller can
send their own value and the proxy appends the real address after it). So we
read from the RIGHT, skipping TRUSTED_PROXY_HOPS entries added by our own
infrastructure (default 1 = Render's load balancer). A spoofed prefix is
therefore ignored. If Render's chain turns out to be longer, every visitor
would share one bucket (too strict, never too loose) — raise
TRUSTED_PROXY_HOPS after checking.

Config (env, all optional):
  SUBMIT_LIMIT_PER_IP, SUBMIT_LIMIT_GLOBAL, SUBMIT_LIMIT_WINDOW_SECONDS,
  TRUSTED_PROXY_HOPS
"""

import math
import os
import threading
import time
from collections import deque

from fastapi import HTTPException, Request


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float, max_keys: int = 10_000, clock=time.monotonic):
        if limit < 1 or window_seconds <= 0:
            raise ValueError("limit must be >= 1 and window_seconds > 0")
        self.limit = limit
        self.window = float(window_seconds)
        self.max_keys = max_keys
        self._clock = clock
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> float:
        """Record one hit for `key`. Returns 0.0 if allowed, otherwise the
        number of seconds until a slot frees up (and records nothing)."""
        now = self._clock()
        cutoff = now - self.window
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                if len(self._hits) >= self.max_keys:
                    self._make_room(cutoff)
                q = self._hits[key] = deque()
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= self.limit:
                return max(q[0] + self.window - now, 0.001)
            q.append(now)
            return 0.0

    def _make_room(self, cutoff: float) -> None:
        """Drop keys with no live hits; if the table is still full of live
        keys, evict the oldest-inserted one so memory stays bounded."""
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= cutoff]:
            del self._hits[k]
        if len(self._hits) >= self.max_keys:
            del self._hits[next(iter(self._hits))]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def _build() -> tuple[SlidingWindowLimiter, SlidingWindowLimiter]:
    window = _int_env("SUBMIT_LIMIT_WINDOW_SECONDS", 3600)
    return (
        SlidingWindowLimiter(max(_int_env("SUBMIT_LIMIT_PER_IP", 5), 1), window),
        SlidingWindowLimiter(max(_int_env("SUBMIT_LIMIT_GLOBAL", 100), 1), window),
    )


submit_per_ip, submit_global = _build()


def reset_all() -> None:
    """Clear both limiters (used by tests)."""
    submit_per_ip.reset()
    submit_global.reset()


def client_ip(request: Request) -> str:
    """Best-effort real client address; see module docstring for the trust model."""
    hops = _int_env("TRUSTED_PROXY_HOPS", 1)
    parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if hops > 0 and len(parts) >= hops:
        return parts[-hops]
    return request.client.host if request.client else "unknown"


def limit_submissions(request: Request) -> None:
    """FastAPI dependency for POST /submit. Per-IP first, so a client that is
    already blocked never consumes the shared global budget."""
    wait = submit_per_ip.check(client_ip(request))
    scope = "from this address"
    if not wait:
        wait = submit_global.check("*")
        scope = "across all clients"
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"Too many submissions {scope}. Try again later.",
            headers={"Retry-After": str(math.ceil(wait))},
        )
