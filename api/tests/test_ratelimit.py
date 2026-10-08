"""
Tests for ratelimit.py and its wiring into POST /submit.
Pins: the window math, that rejected hits are not recorded, that a spoofed
X-Forwarded-For prefix cannot dodge the per-IP limit, and the global backstop.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ratelimit
from db import get_write_client
from main import app
from ratelimit import SlidingWindowLimiter

ADDR = "0x" + "ab" * 20


class FakeClock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


# ---- limiter unit tests ----------------------------------------------------

def test_allows_up_to_limit_then_blocks_with_retry_after():
    clock = FakeClock()
    lim = SlidingWindowLimiter(3, 60, clock=clock)
    assert [lim.check("a") for _ in range(3)] == [0.0, 0.0, 0.0]
    wait = lim.check("a")
    assert wait == pytest.approx(60.0)


def test_slot_frees_after_window():
    clock = FakeClock()
    lim = SlidingWindowLimiter(1, 60, clock=clock)
    assert lim.check("a") == 0.0
    clock.t += 30
    assert lim.check("a") == pytest.approx(30.0)
    clock.t += 31
    assert lim.check("a") == 0.0


def test_rejected_hits_are_not_recorded():
    clock = FakeClock()
    lim = SlidingWindowLimiter(1, 60, clock=clock)
    lim.check("a")
    for _ in range(50):          # hammering while blocked...
        clock.t += 1
        lim.check("a")
    clock.t = 1000.0 + 61        # ...must not extend the block past the first hit's expiry
    assert lim.check("a") == 0.0


def test_keys_are_independent():
    lim = SlidingWindowLimiter(1, 60, clock=FakeClock())
    assert lim.check("a") == 0.0
    assert lim.check("b") == 0.0
    assert lim.check("a") > 0


def test_memory_stays_bounded():
    lim = SlidingWindowLimiter(1, 60, max_keys=5, clock=FakeClock())
    for i in range(50):
        lim.check(f"ip{i}")
    assert len(lim._hits) <= 5


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        SlidingWindowLimiter(0, 60)


# ---- client_ip -------------------------------------------------------------

class _Req:
    def __init__(self, xff=None, host="9.9.9.9"):
        self.headers = {"x-forwarded-for": xff} if xff is not None else {}
        self.client = type("C", (), {"host": host})()


def test_client_ip_reads_from_the_right_and_ignores_spoofed_prefix(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    assert ratelimit.client_ip(_Req("6.6.6.6, 1.2.3.4")) == "1.2.3.4"
    assert ratelimit.client_ip(_Req("1.2.3.4")) == "1.2.3.4"


def test_client_ip_two_hops(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
    assert ratelimit.client_ip(_Req("6.6.6.6, 1.2.3.4, 10.0.0.1")) == "1.2.3.4"


def test_client_ip_falls_back_to_socket_peer(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    assert ratelimit.client_ip(_Req(None, host="7.7.7.7")) == "7.7.7.7"
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
    assert ratelimit.client_ip(_Req("1.2.3.4", host="7.7.7.7")) == "7.7.7.7"


def test_warns_once_when_key_is_an_internal_address(monkeypatch, caplog):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    monkeypatch.setattr(ratelimit, "_warned_internal", False)
    with caplog.at_level("WARNING", logger="isogram.ratelimit"):
        ratelimit.client_ip(_Req("1.2.3.4, 10.31.84.88"))
        ratelimit.client_ip(_Req("1.2.3.4, 10.27.194.106"))
    assert len([r for r in caplog.records if "TRUSTED_PROXY_HOPS" in r.message]) == 1


def test_no_warning_for_a_public_address(monkeypatch, caplog):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "3")
    monkeypatch.setattr(ratelimit, "_warned_internal", False)
    with caplog.at_level("WARNING", logger="isogram.ratelimit"):
        assert ratelimit.client_ip(_Req("6.6.6.6, 105.127.11.4, 172.71.146.149, 10.31.84.88")) == "105.127.11.4"
    assert not caplog.records


# ---- /submit wiring --------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_limiters(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    monkeypatch.setattr(ratelimit, "submit_per_ip", SlidingWindowLimiter(5, 3600))
    monkeypatch.setattr(ratelimit, "submit_global", SlidingWindowLimiter(100, 3600))
    monkeypatch.setattr(
        "routes.submit.insert_submission",
        lambda client, row: {"id": 1, "contract_address": row["contract_address"],
                             "status": "pending", "created_at": "2026-10-08T00:00:00Z"},
    )
    app.dependency_overrides[get_write_client] = lambda: object()
    yield
    app.dependency_overrides.clear()


def _post(c, ip, body=None):
    return c.post("/submit", json=body or {"contract_address": ADDR},
                  headers={"X-Forwarded-For": ip})


def test_sixth_submission_from_one_ip_gets_429_with_retry_after():
    c = TestClient(app)
    assert [_post(c, "1.1.1.1").status_code for _ in range(5)] == [201] * 5
    r = _post(c, "1.1.1.1")
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    assert _post(c, "2.2.2.2").status_code == 201      # other clients unaffected


def test_spoofed_forwarded_for_prefix_does_not_dodge_the_limit():
    c = TestClient(app)
    for i in range(5):
        assert _post(c, f"10.0.0.{i}, 1.1.1.1").status_code == 201   # fake prefix, same real IP
    assert _post(c, "10.0.0.99, 1.1.1.1").status_code == 429


def test_global_cap_is_a_backstop_for_rotating_ips(monkeypatch):
    monkeypatch.setattr(ratelimit, "submit_global", SlidingWindowLimiter(3, 3600))
    c = TestClient(app)
    assert [_post(c, f"3.3.3.{i}").status_code for i in range(3)] == [201] * 3
    r = _post(c, "3.3.3.200")
    assert r.status_code == 429 and "all clients" in r.json()["detail"]


def test_blocked_client_cannot_burn_the_global_budget(monkeypatch):
    monkeypatch.setattr(ratelimit, "submit_per_ip", SlidingWindowLimiter(1, 3600))
    monkeypatch.setattr(ratelimit, "submit_global", SlidingWindowLimiter(3, 3600))
    c = TestClient(app)
    assert _post(c, "4.4.4.4").status_code == 201
    for _ in range(20):
        assert _post(c, "4.4.4.4").status_code == 429       # blocked per-IP...
    assert _post(c, "5.5.5.5").status_code == 201           # ...global budget still has room


def test_oversized_socials_rejected():
    c = TestClient(app)
    r = _post(c, "6.6.6.6", {"contract_address": ADDR, "socials": {"x": "a" * 3000}})
    assert r.status_code == 422


def test_head_health_is_200_for_uptime_monitors():
    c = TestClient(app)
    assert c.head("/health").status_code == 200
    assert c.get("/health").json() == {"status": "ok"}
