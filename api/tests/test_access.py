"""
Tests for access.py / apikeys.py / routes/keys.py: tiered rate limits, API key identification,
key registration and revocation. No network, no database: key lookups and inserts are monkeypatched.
"""

import hashlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import access
import apikeys
import routes.keys as keys_route
import routes.projects as projects_route
from db import get_client, get_write_client
from main import app
from ratelimit import SlidingWindowLimiter

ADDR = "0x" + "ab" * 20
URL = f"/projects/by-address/{ADDR}"   # a cheap route: with the lookup patched to None it is a 404, which still counts
GOOD = apikeys.generate_key()


@pytest.fixture(autouse=True)
def wiring(monkeypatch):
    app.dependency_overrides[get_client] = lambda: "dummy"
    app.dependency_overrides[get_write_client] = lambda: "dummy-write"
    monkeypatch.setattr(access, "get_write_client", lambda: "dummy-write")
    monkeypatch.setattr(projects_route, "fetch_project_ref_by_address", lambda c, a: None)
    monkeypatch.delenv("INTERNAL_API_KEYS", raising=False)
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def record(id=1, **kw):
    return {"id": id, "name": "t", "tier": "registered", "rate_limit_per_minute": None, "revoked_at": None,
            "last_used_at": "2099-01-01T00:00:00+00:00", **kw}


# ---- anonymous tier -----------------------------------------------------------------------------------

def test_anonymous_limit_then_429_with_headers(client, monkeypatch):
    monkeypatch.setenv("ANON_LIMIT_PER_MIN", "3")
    for i in range(3):
        r = client.get(URL)
        assert r.status_code == 404
        assert r.headers["X-RateLimit-Limit"] == "3"
        assert r.headers["X-RateLimit-Remaining"] == str(2 - i)
        assert r.headers["X-RateLimit-Tier"] == "anonymous"
    r = client.get(URL)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1
    assert r.headers["X-RateLimit-Remaining"] == "0"
    assert "API key" in r.json()["detail"]


def test_health_and_root_are_exempt(client, monkeypatch):
    monkeypatch.setenv("ANON_LIMIT_PER_MIN", "1")
    for _ in range(10):
        assert client.get("/health").status_code == 200
        assert client.get("/").status_code == 200


def test_badge_requests_use_their_own_larger_budget(client, monkeypatch):
    import routes.badge as badge_route

    monkeypatch.setenv("ANON_LIMIT_PER_MIN", "1")
    monkeypatch.setenv("BADGE_LIMIT_PER_MIN", "4")
    monkeypatch.setattr(badge_route, "fetch_project", lambda c, pid: None)
    for _ in range(4):
        r = client.get("/badge/nope.svg")
        assert r.headers["X-RateLimit-Tier"] == "badge"
    assert client.get("/badge/nope.svg").status_code == 429
    assert client.get(URL).status_code == 404  # the anonymous budget is untouched by badges


# ---- keys ---------------------------------------------------------------------------------------------

def test_unknown_key_is_401_not_a_silent_downgrade(client, monkeypatch):
    monkeypatch.setattr(apikeys, "fetch_key_by_hash", lambda c, h: None)
    r = client.get(URL, headers={"X-API-Key": GOOD})
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "ApiKey"


def test_malformed_key_is_401_without_touching_the_database(client, monkeypatch):
    def boom(c, h):
        raise AssertionError("malformed keys must not reach the database")

    monkeypatch.setattr(apikeys, "fetch_key_by_hash", boom)
    assert client.get(URL, headers={"X-API-Key": "not-a-key"}).status_code == 401


def test_registered_key_gets_the_higher_limit_and_its_own_bucket(client, monkeypatch):
    monkeypatch.setenv("ANON_LIMIT_PER_MIN", "1")
    monkeypatch.setenv("KEY_LIMIT_PER_MIN", "5")
    monkeypatch.setattr(apikeys, "fetch_key_by_hash", lambda c, h: record(id=7))
    for i in range(5):
        r = client.get(URL, headers={"X-API-Key": GOOD})
        assert r.status_code == 404
        assert r.headers["X-RateLimit-Tier"] == "registered"
        assert r.headers["X-RateLimit-Limit"] == "5"
    assert client.get(URL, headers={"X-API-Key": GOOD}).status_code == 429
    assert client.get(URL).status_code == 404  # same address, but anonymous traffic has its own bucket


def test_two_keys_do_not_share_a_budget(client, monkeypatch):
    monkeypatch.setenv("KEY_LIMIT_PER_MIN", "1")
    other = apikeys.generate_key()
    ids = {apikeys.hash_key(GOOD): 1, apikeys.hash_key(other): 2}
    monkeypatch.setattr(apikeys, "fetch_key_by_hash", lambda c, h: record(id=ids[h]))
    assert client.get(URL, headers={"X-API-Key": GOOD}).status_code == 404
    assert client.get(URL, headers={"X-API-Key": GOOD}).status_code == 429
    assert client.get(URL, headers={"X-API-Key": other}).status_code == 404


def test_per_key_limit_override(client, monkeypatch):
    monkeypatch.setattr(apikeys, "fetch_key_by_hash", lambda c, h: record(rate_limit_per_minute=2, tier="partner"))
    assert client.get(URL, headers={"X-API-Key": GOOD}).headers["X-RateLimit-Limit"] == "2"
    assert client.get(URL, headers={"X-API-Key": GOOD}).status_code == 404
    assert client.get(URL, headers={"X-API-Key": GOOD}).status_code == 429


def test_revoked_key_is_401(client, monkeypatch):
    monkeypatch.setattr(apikeys, "fetch_key_by_hash", lambda c, h: record(revoked_at="2026-10-01T00:00:00+00:00"))
    assert client.get(URL, headers={"X-API-Key": GOOD}).status_code == 401


def test_key_lookups_are_cached(client, monkeypatch):
    calls = []
    monkeypatch.setattr(apikeys, "fetch_key_by_hash", lambda c, h: calls.append(h) or record())
    for _ in range(5):
        client.get(URL, headers={"X-API-Key": GOOD})
    assert len(calls) == 1


def test_internal_key_needs_no_database_and_gets_the_internal_tier(client, monkeypatch):
    secret = "dashboard-secret-value"
    monkeypatch.setenv("INTERNAL_API_KEYS", f"other, {secret}")

    def boom(c, h):
        raise AssertionError("internal keys never touch the database")

    monkeypatch.setattr(apikeys, "fetch_key_by_hash", boom)
    r = client.get(URL, headers={"X-API-Key": secret})
    assert r.status_code == 404
    assert r.headers["X-RateLimit-Tier"] == "internal"
    assert r.headers["X-RateLimit-Limit"] == "6000"


def test_database_outage_serves_the_request_as_anonymous(client, monkeypatch):
    def down(c, h):
        raise RuntimeError("db down")

    monkeypatch.setattr(apikeys, "fetch_key_by_hash", down)
    r = client.get(URL, headers={"X-API-Key": GOOD})
    assert r.status_code == 404
    assert r.headers["X-RateLimit-Tier"] == "anonymous"


def test_cache_misses_are_budgeted_so_random_keys_cannot_hammer_the_database(client, monkeypatch):
    monkeypatch.setenv("LOOKUP_LIMIT_PER_MIN", "2")
    calls = []
    monkeypatch.setattr(apikeys, "fetch_key_by_hash", lambda c, h: calls.append(h))
    codes = [client.get(URL, headers={"X-API-Key": apikeys.generate_key()}).status_code for _ in range(4)]
    assert codes == [401, 401, 429, 429]
    assert len(calls) == 2


# ---- admin routes -------------------------------------------------------------------------------------

def test_admin_routes_have_their_own_per_ip_limit(client, monkeypatch):
    monkeypatch.setenv("ADMIN_LIMIT_PER_MIN", "2")
    monkeypatch.setenv("ADMIN_API_KEY", "right")
    assert client.get("/admin/keys", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert client.get("/admin/keys", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert client.get("/admin/keys", headers={"X-Admin-Key": "wrong"}).status_code == 429
    assert client.get(URL).status_code == 404  # public routes are unaffected


def test_admin_can_list_and_revoke(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "right")
    h = {"X-Admin-Key": "right"}
    monkeypatch.setattr(apikeys, "list_keys", lambda c: [{"id": 1, "key_prefix": "isg_abcd", "name": "x", "email": "a@b.co"}])
    assert client.get("/admin/keys", headers=h).json()[0]["key_prefix"] == "isg_abcd"
    assert "key_hash" not in str(client.get("/admin/keys", headers=h).json())

    monkeypatch.setattr(apikeys, "revoke_key", lambda c, i: {"id": i, "revoked_at": "2026-10-13T00:00:00+00:00"} if i == 1 else None)
    assert client.post("/admin/keys/1/revoke", headers=h).json()["id"] == 1
    assert client.post("/admin/keys/2/revoke", headers=h).status_code == 404
    assert client.post("/admin/keys/1/revoke").status_code == 401


def test_revoke_takes_effect_immediately_despite_the_cache(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "right")
    state = {"revoked": None}
    monkeypatch.setattr(apikeys, "fetch_key_by_hash", lambda c, h: record(id=1, revoked_at=state["revoked"]))
    assert client.get(URL, headers={"X-API-Key": GOOD}).status_code == 404
    state["revoked"] = "2026-10-13T00:00:00+00:00"
    monkeypatch.setattr(apikeys, "revoke_key", lambda c, i: {"id": i, "revoked_at": state["revoked"]})
    client.post("/admin/keys/1/revoke", headers={"X-Admin-Key": "right"})
    assert client.get(URL, headers={"X-API-Key": GOOD}).status_code == 401


# ---- registration -------------------------------------------------------------------------------------

def test_create_key_returns_the_key_once_and_stores_only_its_hash(client, monkeypatch):
    stored = {}

    def fake_insert(c, row):
        stored.update(row)
        return {**row, "id": 3, "created_at": "2026-10-13T00:00:00+00:00"}

    monkeypatch.setattr(apikeys, "insert_key", fake_insert)
    monkeypatch.setattr(apikeys, "count_active_for_email", lambda c, e: 0)
    r = client.post("/keys", json={"name": "  Acme   tracker ", "email": "  Dev@Acme.IO "})
    assert r.status_code == 201
    body = r.json()
    assert body["api_key"].startswith("isg_") and len(body["api_key"]) >= 30
    assert body["name"] == "Acme tracker"
    assert body["rate_limit_per_minute"] == 600
    assert r.headers["Cache-Control"] == "no-store"
    assert stored["key_hash"] == hashlib.sha256(body["api_key"].encode()).hexdigest()
    assert body["api_key"] not in str(stored)            # the plaintext key is never stored
    assert stored["key_prefix"] == body["api_key"][:8]
    assert stored["email"] == "dev@acme.io"              # trimmed and lowercased
    assert "email" not in body                            # the address is never echoed back


@pytest.mark.parametrize("payload", [
    {}, {"name": "ok"}, {"email": "a@b.co"},
    {"name": "", "email": "a@b.co"}, {"name": "a", "email": "a@b.co"}, {"name": "   ", "email": "a@b.co"}, {"name": "x" * 61, "email": "a@b.co"},
    {"name": "ok", "email": ""}, {"name": "ok", "email": "not-an-email"}, {"name": "ok", "email": "a@b"}, {"name": "ok", "email": "a b@c.com"},
    {"name": "ok", "email": "a@@b.com"}, {"name": "ok", "email": "x" * 250 + "@b.com"},
])
def test_create_key_validates_input(client, monkeypatch, payload):
    monkeypatch.setattr(apikeys, "insert_key", lambda c, row: pytest.fail("must not insert invalid input"))
    assert client.post("/keys", json=payload).status_code == 422


def test_key_creation_is_limited_per_ip(client, monkeypatch):
    monkeypatch.setattr(apikeys, "insert_key", lambda c, row: {**row, "id": 1, "created_at": "2026-10-13T00:00:00+00:00"})
    monkeypatch.setattr(apikeys, "count_active_for_email", lambda c, e: 0)
    monkeypatch.setattr(keys_route, "create_per_ip", SlidingWindowLimiter(2, 86400))
    assert client.post("/keys", json={"name": "one", "email": "a@b.co"}).status_code == 201
    assert client.post("/keys", json={"name": "two", "email": "a@b.co"}).status_code == 201
    r = client.post("/keys", json={"name": "three", "email": "a@b.co"})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_an_email_can_hold_only_a_few_active_keys(client, monkeypatch):
    monkeypatch.setattr(apikeys, "insert_key", lambda c, row: pytest.fail("must not insert past the per-email cap"))
    monkeypatch.setattr(apikeys, "count_active_for_email", lambda c, e: 3)
    r = client.post("/keys", json={"name": "four", "email": "a@b.co"})
    assert r.status_code == 409
    monkeypatch.setenv("KEY_MAX_PER_EMAIL", "4")
    monkeypatch.setattr(apikeys, "insert_key", lambda c, row: {**row, "id": 1, "created_at": "2026-10-13T00:00:00+00:00"})
    assert client.post("/keys", json={"name": "four", "email": "a@b.co"}).status_code == 201


def test_a_created_key_works_end_to_end(client, monkeypatch):
    rows = {}

    def fake_insert(c, row):
        rows[row["key_hash"]] = {**row, "id": 9, "created_at": "2026-10-13T00:00:00+00:00", "revoked_at": None, "rate_limit_per_minute": None}
        return rows[row["key_hash"]]

    monkeypatch.setattr(apikeys, "insert_key", fake_insert)
    monkeypatch.setattr(apikeys, "fetch_key_by_hash", lambda c, h: rows.get(h))
    monkeypatch.setattr(apikeys, "count_active_for_email", lambda c, e: 0)
    key = client.post("/keys", json={"name": "e2e", "email": "e2e@example.com"}).json()["api_key"]
    r = client.get(URL, headers={"X-API-Key": key})
    assert r.status_code == 404 and r.headers["X-RateLimit-Tier"] == "registered"


def test_key_helpers():
    k = apikeys.generate_key()
    assert apikeys.looks_like_key(k)
    assert not apikeys.looks_like_key(k[:-30])
    assert apikeys.generate_key() != k
