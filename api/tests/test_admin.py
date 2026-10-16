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
    c = _Client({"0x" + "ab" * 20})
    _manual_classify(c, "0x" + "AB" * 20, "dex", "UniversalRouter 0x4fca")
    (op, payload, filters), = c.writes
    assert op == "update" and filters == {"contract_address": "0x" + "ab" * 20}
    assert payload["category"] == "dex" and payload["gecko_name"] == "UniversalRouter 0x4fca"
    assert payload["status"] == "needs_review"
    assert "call_count" not in payload and "first_seen" not in payload  # never clobber discovery's data


def test_unseen_address_is_inserted_with_required_not_null_columns():
    c = _Client(set())
    _manual_classify(c, "0x" + "CD" * 20, "infra", None)
    (op, payload, _), = c.writes
    assert op == "insert" and payload["contract_address"] == "0x" + "cd" * 20
    assert payload["first_seen"] and payload["last_seen"] and payload["call_count"] == 0


def test_classify_route_returns_ok_and_lowercases(monkeypatch):
    c = _Client({"0x" + "ab" * 20})
    app.dependency_overrides[get_write_client] = lambda: c
    try:
        monkeypatch.setenv("ADMIN_API_KEY", "k")
        resp = TestClient(app).post(
            "/admin/classify", headers={"X-Admin-Key": "k"},
            json={"contract_address": "0x" + "AB" * 20, "category": "dex", "name": "X"})
        assert resp.status_code == 200 and resp.json()["contract_address"] == "0x" + "ab" * 20
        bad = TestClient(app).post("/admin/classify", headers={"X-Admin-Key": "wrong"},
                                   json={"contract_address": "0x" + "ab" * 20, "category": "dex"})
        assert bad.status_code == 401
    finally:
        app.dependency_overrides.clear()



# ---- curation desk (2026-10-15): the review flow, with a fake client that records writes in order ----

ADDR = "0x" + "11" * 20
OTHER = "0x" + "22" * 20
HDR = {"X-Admin-Key": "k"}


class _Q:
    def __init__(self, db, name):
        self.db, self.name, self.op, self.payload, self.filters, self._desc, self._limit = db, name, "select", None, {}, False, None

    def select(self, *a): self.op = "select"; return self
    def eq(self, col, val): self.filters[col] = val; return self
    def order(self, col, desc=False): self._desc = desc; return self
    def limit(self, n): self._limit = n; return self
    def update(self, payload): self.op, self.payload = "update", payload; return self
    def insert(self, payload): self.op, self.payload = "insert", payload; return self

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        if self.op == "select":
            out = [r for r in rows if all(r.get(k) == v for k, v in self.filters.items())]
            return _Result(out[: self._limit] if self._limit else out)
        self.db.writes.append((self.name, self.op, self.payload, dict(self.filters)))
        return _Result(None)


class _DB:
    def __init__(self, **tables): self.tables, self.writes = {k: list(v) for k, v in tables.items()}, []
    def table(self, name): return _Q(self, name)


def _sub(**kw):
    base = {"id": 7, "contract_address": ADDR, "proposed_name": "Acme Swap", "proposed_category": "DeFi protocol",
            "socials": {"x": "@acme"}, "submitter_contact": "a@b.co", "note": "hi", "status": "pending",
            "reviewed_at": None, "reviewer_note": None, "created_at": "2026-10-14T21:00:00+00:00"}
    base.update(kw)
    return base


@pytest.fixture
def desk(monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "k")
    state = {}

    def use(db):
        state["db"] = db
        app.dependency_overrides[get_write_client] = lambda: db
        return TestClient(app)

    yield use
    app.dependency_overrides.clear()


def test_admin_submissions_expose_everything_a_reviewer_needs(desk):
    """Regression: response_model=SubmissionResponse used to strip name, category, socials, contact and note."""
    r = desk(_DB(project_submissions=[_sub()])).get("/admin/submissions", headers=HDR)
    row = r.json()[0]
    assert row["proposed_name"] == "Acme Swap" and row["proposed_category"] == "DeFi protocol"
    assert row["socials"] == {"x": "@acme"} and row["submitter_contact"] == "a@b.co" and row["note"] == "hi"


def test_admin_submissions_status_filter_and_validation(desk):
    c = desk(_DB(project_submissions=[_sub(), _sub(id=8, status="rejected")]))
    assert [x["id"] for x in c.get("/admin/submissions", headers=HDR).json()] == [7]
    assert [x["id"] for x in c.get("/admin/submissions?status=rejected", headers=HDR).json()] == [8]
    assert c.get("/admin/submissions?status=bogus", headers=HDR).status_code == 422


def test_categories_endpoint_matches_the_taxonomy(desk):
    from aggregate import SEGMENT_BY_CATEGORY
    rows = desk(_DB()).get("/admin/categories", headers=HDR).json()
    assert {r["category"]: r["segment"] for r in rows} == SEGMENT_BY_CATEGORY


def test_approve_with_free_text_category_is_rejected_and_writes_nothing(desk):
    """The public form sends labels like 'DeFi protocol'; approving that unchanged must not be stored as a category."""
    db = _DB(project_submissions=[_sub()])
    r = desk(db).post("/admin/submissions/7/review", headers=HDR, json={"decision": "approve"})
    assert r.status_code == 422 and "Unknown category" in r.json()["detail"]
    assert db.writes == []


def test_approve_without_any_category_leaves_submission_pending(desk):
    """Regression: the submission used to be marked approved BEFORE the missing-category error."""
    db = _DB(project_submissions=[_sub(proposed_category=None)])
    r = desk(db).post("/admin/submissions/7/review", headers=HDR, json={"decision": "approve"})
    assert r.status_code == 422
    assert db.writes == []


def test_approve_queues_the_contract_first_then_marks_the_submission(desk):
    db = _DB(project_submissions=[_sub()], discovered_contracts=[])
    r = desk(db).post("/admin/submissions/7/review", headers=HDR,
                      json={"decision": "approve", "category": " DEX ", "name": "Acme Swap", "note": "checked"})
    assert r.status_code == 200
    (t1, op1, p1, _), (t2, op2, p2, f2) = db.writes
    assert (t1, op1) == ("discovered_contracts", "insert")
    assert p1["category"] == "dex" and p1["status"] == "needs_review" and p1["gecko_name"] == "Acme Swap"
    assert (t2, op2, f2) == ("project_submissions", "update", {"id": 7})
    assert p2["status"] == "approved" and p2["reviewer_note"] == "checked"


def test_reject_only_touches_the_submission(desk):
    db = _DB(project_submissions=[_sub()])
    r = desk(db).post("/admin/submissions/7/review", headers=HDR, json={"decision": "reject", "note": "not on Arc"})
    assert r.status_code == 200
    (table, op, payload, _), = db.writes
    assert table == "project_submissions" and payload["status"] == "rejected" and payload["reviewer_note"] == "not on Arc"


def test_already_reviewed_and_missing_submissions(desk):
    c = desk(_DB(project_submissions=[_sub(status="approved")]))
    assert c.post("/admin/submissions/7/review", headers=HDR, json={"decision": "reject"}).status_code == 409
    assert c.post("/admin/submissions/99/review", headers=HDR, json={"decision": "reject"}).status_code == 404


def test_classify_validates_category_and_address(desk):
    db = _DB(discovered_contracts=[])
    c = desk(db)
    assert c.post("/admin/classify", headers=HDR, json={"contract_address": ADDR, "category": "DeFi protocol"}).status_code == 422
    assert c.post("/admin/classify", headers=HDR, json={"contract_address": "0xabc", "category": "dex"}).status_code == 422
    assert db.writes == []
    ok = c.post("/admin/classify", headers=HDR, json={"contract_address": ADDR.upper().replace("0X", "0x"), "category": "Lending"})
    assert ok.status_code == 200 and ok.json()["category"] == "lending" and ok.json()["segment"] == "defi"


def test_dismiss_discovered_contract(desk):
    db = _DB(discovered_contracts=[
        {"contract_address": ADDR, "status": "unclassified"},
        {"contract_address": OTHER, "status": "promoted"},
    ])
    c = desk(db)
    assert c.post(f"/admin/discovered/{ADDR}/reject", headers=HDR).status_code == 200
    (table, op, payload, filters), = db.writes
    assert payload["status"] == "rejected" and filters == {"contract_address": ADDR}
    assert c.post(f"/admin/discovered/{OTHER}/reject", headers=HDR).status_code == 409
    assert c.post("/admin/discovered/0x" + "33" * 20 + "/reject", headers=HDR).status_code == 404
    assert c.post("/admin/discovered/nope/reject", headers=HDR).status_code == 422
    assert len(db.writes) == 1


def test_every_admin_route_needs_the_key(desk):
    c = desk(_DB(project_submissions=[_sub()]))
    for method, path in [("get", "/admin/categories"), ("get", "/admin/submissions"), ("get", "/admin/discovered"),
                         ("post", f"/admin/discovered/{ADDR}/reject")]:
        assert getattr(c, method)(path).status_code == 401


def test_restore_sends_a_dismissed_contract_back_to_unclassified_only(desk):
    """Restore never jumps to needs_review: a person must choose a category again before anything is promoted."""
    db = _DB(discovered_contracts=[
        {"contract_address": ADDR, "status": "rejected", "category": "token"},
        {"contract_address": OTHER, "status": "needs_review", "category": "dex"},
    ])
    c = desk(db)
    r = c.post(f"/admin/discovered/{ADDR}/restore", headers=HDR)
    assert r.status_code == 200 and r.json()["restored_to"] == "unclassified"
    (table, op, payload, filters), = db.writes
    assert payload["status"] == "unclassified" and "category" not in payload and filters == {"contract_address": ADDR}
    assert c.post(f"/admin/discovered/{OTHER}/restore", headers=HDR).status_code == 409
    assert c.post("/admin/discovered/0x" + "33" * 20 + "/restore", headers=HDR).status_code == 404
    assert c.post("/admin/discovered/nope/restore", headers=HDR).status_code == 422
    assert c.post(f"/admin/discovered/{ADDR}/restore").status_code == 401
    assert len(db.writes) == 1
