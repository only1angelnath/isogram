"""
apikeys.py - API key generation, storage and lookup.

A key looks like `isg_` + 32 URL-safe characters (192 bits of randomness). Only its SHA-256 hash is
stored (a fast hash is appropriate precisely because the key is long and random, so there is nothing
to brute-force), plus the first 8 characters so a person can recognise which key is which. The full
key is shown once, at creation, and can never be recovered.

Lookups go through a small in-process cache (60 s, bounded) so a busy key does not cost a database
read per request. Revocation therefore takes effect within a minute, or immediately on this instance
when it goes through the admin route (which clears the cache). The API is a single Render instance;
if it ever scales out, each instance would expire its own cache, so the 60 s bound still holds.

The api_keys table has RLS on and no policies, so only the service key can touch it; every function
here takes the write client (db.get_write_client).
"""

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone

KEY_PREFIX = "isg_"
_KEY_RE = re.compile(r"^isg_[A-Za-z0-9_-]{20,64}$")
CACHE_TTL_SECONDS = 60
CACHE_MAX_ENTRIES = 5000
TOUCH_INTERVAL_SECONDS = 3600


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(24)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def looks_like_key(value: str) -> bool:
    """Cheap shape check so garbage never reaches the database."""
    return bool(_KEY_RE.match(value))


def internal_keys() -> list[str]:
    """Keys that belong to Isogram's own services (the dashboard), from INTERNAL_API_KEYS (comma separated)."""
    return [k.strip() for k in os.environ.get("INTERNAL_API_KEYS", "").split(",") if k.strip()]


def match_internal(key: str) -> bool:
    ok = False
    for candidate in internal_keys():
        ok |= hmac.compare_digest(candidate.encode(), key.encode())  # no early exit: constant time per candidate
    return ok


# ---- database access (service-key client) ---------------------------------------------------------

def insert_key(client, row: dict) -> dict:
    result = client.table("api_keys").insert(row).execute()
    return result.data[0] if result.data else {}


def fetch_key_by_hash(client, key_hash: str) -> dict | None:
    result = (
        client.table("api_keys")
        .select("id, name, tier, rate_limit_per_minute, revoked_at, last_used_at")
        .eq("key_hash", key_hash)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def touch_key(client, key_id: int) -> None:
    client.table("api_keys").update({"last_used_at": datetime.now(timezone.utc).isoformat()}).eq("id", key_id).execute()


def count_active_for_email(client, email: str) -> int:
    result = (
        client.table("api_keys")
        .select("id", count="exact")
        .eq("email", email)
        .is_("revoked_at", "null")
        .limit(1)
        .execute()
    )
    return int(result.count or 0)


def list_keys(client) -> list[dict]:
    result = (
        client.table("api_keys")
        .select("id, key_prefix, name, email, tier, rate_limit_per_minute, created_at, last_used_at, revoked_at")
        .order("id")
        .execute()
    )
    return result.data or []


def revoke_key(client, key_id: int) -> dict | None:
    result = (
        client.table("api_keys")
        .update({"revoked_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", key_id)
        .is_("revoked_at", "null")
        .execute()
    )
    return result.data[0] if result.data else None


# ---- lookup cache ----------------------------------------------------------------------------------

class KeyDirectory:
    """hash -> key record (or None for 'no such key'), cached for CACHE_TTL_SECONDS."""

    def __init__(self, ttl: float = CACHE_TTL_SECONDS, max_entries: int = CACHE_MAX_ENTRIES, clock=time.monotonic):
        self.ttl = ttl
        self.max_entries = max_entries
        self._clock = clock
        self._entries: dict[str, tuple[float, dict | None]] = {}
        self._lock = threading.Lock()

    def cached(self, key_hash: str):
        """(hit, record). A hit with record None means 'known not to exist'."""
        with self._lock:
            entry = self._entries.get(key_hash)
            if entry and entry[0] > self._clock():
                return True, entry[1]
            return False, None

    def store(self, key_hash: str, record: dict | None) -> None:
        with self._lock:
            if len(self._entries) >= self.max_entries:
                now = self._clock()
                for k in [k for k, (exp, _) in self._entries.items() if exp <= now]:
                    del self._entries[k]
                if len(self._entries) >= self.max_entries:
                    del self._entries[next(iter(self._entries))]
            self._entries[key_hash] = (self._clock() + self.ttl, record)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


directory = KeyDirectory()
