"""
Tests for routes/admin.py::_manual_classify - the 2026-10-06 500-error fix.
The admin routes had no tests; this pins the update-vs-insert behaviour.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import get_write_client
from main import app
from routes.admin import _manual_classify


class _Result:
    def __init__(self, data): self.data = data


class _Table:
    def __init__(self, client): self.client = client; self.op = None; self.payload = None; self.filters = {}

    def select(self, *a): self.op = "select"; return self
    def eq(self, col, val): self.filters[col] = val; return self
    def update(self, payload): self.op, self.payload = "update", payload; return self
    def insert(self, payload): self.op, self.payload = "insert", payload; return self
    def upsert(self, *a, **k): raise AssertionError("must not upsert: ON CONFLICT trips NOT NULL on first_seen")

    def execute(self):
        if self.op == "select":
            return _Result([{"contract_address": a} for a in self.client.existing
                            if a == self.filters.get("contract_address")])
        self.client.writes.append((self.op, self.payload, dict(self.filters)))
        return _Result(None)


class _Client:
    def __init__(self, existing): self.existing, self.writes = set(existing), []
    def table(self, name):
        assert name == "discovered_contracts"
        return _Table(self)


def test_existing_address_is_updated_not_inserted_and_keeps_call_count():
    c = _Client({"0xabc"})
    _manual_classify(c, "0xABC", "dex", "UniversalRouter 0x4fca")
    (op, payload, filters), = c.writes
    assert op == "update" and filters == {"contract_address": "0xabc"}
    assert payload["category"] == "dex" and payload["gecko_name"] == "UniversalRouter 0x4fca"
    assert payload["status"] == "needs_review"
    assert "call_count" not in payload and "first_seen" not in payload  # never clobber discovery's data


def test_unseen_address_is_inserted_with_required_not_null_columns():
    c = _Client(set())
    _manual_classify(c, "0xNEW", "infra", None)
    (op, payload, _), = c.writes
    assert op == "insert" and payload["contract_address"] == "0xnew"
    assert payload["first_seen"] and payload["last_seen"] and payload["call_count"] == 0


def test_classify_route_returns_ok_and_lowercases(monkeypatch):
    c = _Client({"0xabc"})
    app.dependency_overrides[get_write_client] = lambda: c
    try:
        monkeypatch.setenv("ADMIN_API_KEY", "k")
        resp = TestClient(app).post(
            "/admin/classify", headers={"X-Admin-Key": "k"},
            json={"contract_address": "0xABC", "category": "dex", "name": "X"})
        assert resp.status_code == 200 and resp.json()["contract_address"] == "0xabc"
        bad = TestClient(app).post("/admin/classify", headers={"X-Admin-Key": "wrong"},
                                   json={"contract_address": "0xabc", "category": "dex"})
        assert bad.status_code == 401
    finally:
        app.dependency_overrides.clear()
