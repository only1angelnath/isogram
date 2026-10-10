"""
ops/seed_launchpads.py against an in-memory fake database that ENFORCES the two rules that
matter: the seeded-project trigger (no category/contracts change on a seeded row) and the
foreign keys without ON DELETE CASCADE. No network, no real database.
"""

import importlib.util
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[2] / "ops" / "seed_launchpads.py"
spec = importlib.util.spec_from_file_location("seed_launchpads", OPS)
sl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sl)

P8, P7 = sl.ARGUS_PORTALS["#8 (launch portal)"].lower(), sl.ARGUS_PORTALS["#7"].lower()
FAZE, UBI_REAL = sl.TOKENS["faze"], sl.TOKENS["ubi"]
UBI_COPY = "0x14c8a4ce07ad3be3b3f2bbbac9732f09ae0f234c"


def proj(id, name, category, contracts, seeded=False, socials=None):
    return {"id": id, "name": name, "category": category, "contracts": list(contracts), "seeded": seeded, "socials": socials or {}}


def baseline():
    return {
        "projects": [
            proj("argus", "Argus", "token", [sl.ARGUS_TOKEN]),
            proj("argusv5portal", "ArgusV5Portal", "bridge", [P8]),
            proj("argusv4portal7", "ArgusV4Portal7", "bridge", [P7]),
            proj("faze", "Faze", "token", [FAZE]),
            proj("ubi", "UBI", "token", [UBI_REAL]),
            proj("ubi-copy", "UBI.fun on Arc", "token", [UBI_COPY]),
            proj("parabolic", "Parabolic", "token", ["0x" + "9" * 40]),
        ],
        "discovered_contracts": [{"id": 1, "promoted_project_id": "argusv5portal"}, {"id": 2, "promoted_project_id": "faze"}],
        "project_scores": [{"id": 1, "project_id": "argusv5portal"}, {"id": 2, "project_id": "faze"}],
        "gas_events": [{"id": 1, "project_id": "argusv4portal7"}],
    }


class Query:
    def __init__(self, db, table):
        self.db, self.t, self.mode, self.vals = db, table, "select", None
        self.filters, self.after, self.n = [], None, None

    def select(self, *a): return self
    def eq(self, c, v): self.filters.append((c, v)); return self
    def gt(self, c, v): self.after = (c, v); return self
    def order(self, c): return self
    def limit(self, n): self.n = n; return self
    def update(self, v): self.mode, self.vals = "update", v; return self
    def insert(self, v): self.mode, self.vals = "insert", v; return self
    def delete(self): self.mode = "delete"; return self

    def _rows(self):
        rows = self.db[self.t]
        for c, v in self.filters:
            rows = [r for r in rows if r.get(c) == v]
        if self.after:
            rows = [r for r in rows if r[self.after[0]] > self.after[1]]
        return rows

    def execute(self):
        rows = self._rows()
        if self.mode == "select":
            return type("R", (), {"data": [dict(r) for r in rows[: self.n]]})()
        if self.mode == "insert":
            assert not any(r["id"] == self.vals["id"] for r in self.db[self.t]), "duplicate id"
            self.db[self.t].append(dict(self.vals))
        elif self.mode == "update":
            if self.t == "gas_events" and self.db.get("_gas_broken"):
                raise RuntimeError("statement timeout")                  # fails BEFORE touching any row
            for r in rows:
                if self.t == "projects" and r["seeded"] and any(k in self.vals and self.vals[k] != r[k] for k in ("contracts", "category")):
                    raise RuntimeError(f"Refusing to change contracts/category on seeded project {r['id']}")
                r.update(self.vals)
        elif self.mode == "delete":
            for r in rows:
                if self.t == "projects":
                    for ref, col in (("discovered_contracts", "promoted_project_id"), ("project_scores", "project_id"), ("gas_events", "project_id")):
                        if any(x.get(col) == r["id"] for x in self.db[ref]):
                            raise RuntimeError(f"FK violation: {ref}.{col} still references {r['id']}")
                self.db[self.t].remove(r)
        return type("R", (), {"data": None})()


class FakeClient:
    def __init__(self, db): self.db = db
    def table(self, name): return Query(self.db, name)


def chain(call_overrides=None, no_code=()):
    def call(method, params):
        if method == "eth_chainId":
            return (call_overrides or {}).get("chain", sl.CHAIN_ID)
        return "0x" if params[0].lower() in {a.lower() for a in no_code} else "0x6080" + "00" * 40
    return call


def by_id(db, pid): return next((p for p in db["projects"] if p["id"] == pid), None)


def test_plan_picks_the_right_projects_and_leaves_copycats_alone():
    plan = sl.build_plan(baseline()["projects"])
    assert sorted(p["id"] for p in plan["tokens"]) == ["faze", "ubi"]
    assert "ubi-copy" not in [p["id"] for p in plan["tokens"]]
    assert plan["argus"]["contracts"][0] == sl.ARGUS_TOKEN and len(plan["argus"]["contracts"]) == 9   # token + 8 portals
    assert sorted(r["id"] for r in plan["retire"]) == ["argusv4portal7", "argusv5portal"]
    assert [m[0] for m in plan["missing"]] and "arcstocks" in [m[0] for m in plan["missing"]]
    assert plan["bullcheese"]["existing"] is None and len(plan["bullcheese"]["contracts"]) == 6
    assert [u[0] for u in plan["unmapped"]] == ["Parabolic"]


def test_preview_writes_nothing_but_still_validates_on_chain(capsys):
    db = baseline(); before = repr(db)
    sl.run(FakeClient(db), apply=False, call=chain())
    assert repr(db) == before
    out = capsys.readouterr().out
    assert "all have contract code" in out and "PREVIEW ONLY" in out


def test_apply_makes_the_expected_changes_and_respects_the_trigger_and_foreign_keys():
    db = baseline()
    sl.run(FakeClient(db), apply=True, call=chain())
    faze = by_id(db, "faze")
    assert faze["category"] == "launchpad" and faze["seeded"] is True
    argus = by_id(db, "argus")
    assert argus["category"] == "launchpad" and argus["seeded"] and len(argus["contracts"]) == 9
    assert argus["socials"]["website"] == "https://argus.world/"
    assert by_id(db, "argusv5portal") is None and by_id(db, "argusv4portal7") is None           # stubs retired
    assert db["discovered_contracts"][0]["promoted_project_id"] == "argus"                     # ledger repointed
    assert db["gas_events"][0]["project_id"] == "argus"
    assert [s["project_id"] for s in db["project_scores"]] == ["faze"]                          # stub scores dropped
    bull = by_id(db, "bullcheese")
    assert bull["seeded"] and bull["category"] == "launchpad" and len(bull["contracts"]) == 6
    assert by_id(db, "ubi-copy")["category"] == "token"                                         # copycat untouched
    assert by_id(db, "ubi")["category"] == "launchpad"


def test_second_apply_is_a_no_op():
    db = baseline()
    sl.run(FakeClient(db), apply=True, call=chain())
    snapshot = repr(db)
    plan = sl.run(FakeClient(db), apply=True, call=chain())
    assert repr(db) == snapshot
    assert not plan["tokens"] and plan["argus"] is None and plan["bullcheese"] is None
    assert {"Faze", "UBI", "Argus", "BullCheese"} <= set(plan["done"])


def test_a_hand_seeded_project_under_another_category_is_skipped_not_forced():
    db = baseline()
    by_id(db, "faze").update(seeded=True)                      # curated as 'token'
    sl.run(FakeClient(db), apply=True, call=chain())           # would raise from the trigger if it tried
    assert by_id(db, "faze")["category"] == "token"


def test_a_portal_owned_by_a_seeded_project_is_a_conflict_and_is_left_out():
    db = baseline()
    db["projects"].append(proj("other", "Somebody Else", "infra", [sl.ARGUS_PORTALS["#5"].lower()], seeded=True))
    plan = sl.run(FakeClient(db), apply=True, call=chain())
    assert (sl.ARGUS_PORTALS["#5"], "Somebody Else") in plan["conflicts"]
    assert sl.ARGUS_PORTALS["#5"].lower() not in by_id(db, "argus")["contracts"]
    assert by_id(db, "other")["contracts"] == [sl.ARGUS_PORTALS["#5"].lower()]


def test_a_stub_with_foreign_contracts_is_not_deleted():
    db = baseline()
    by_id(db, "argusv5portal")["contracts"].append("0x" + "7" * 40)   # stub also owns something else
    plan = sl.run(FakeClient(db), apply=True, call=chain())
    assert by_id(db, "argusv5portal") is not None
    assert (sl.ARGUS_PORTALS["#8 (launch portal)"], "ArgusV5Portal") in plan["conflicts"]


def test_legacy_gas_events_failure_stops_loudly_before_argus_is_touched():
    db = baseline(); db["_gas_broken"] = True                   # gas_events rows still reference the Portal #7 stub
    with pytest.raises(RuntimeError, match="FK violation"):
        sl.run(FakeClient(db), apply=True, call=chain())
    argus = by_id(db, "argus")
    assert argus["category"] == "token" and argus["contracts"] == [sl.ARGUS_TOKEN]   # not half-merged
    assert by_id(db, "bullcheese") is None
    db["_gas_broken"] = False                                    # fixed: a re-run completes
    sl.run(FakeClient(db), apply=True, call=chain())
    assert by_id(db, "argus")["category"] == "launchpad" and by_id(db, "bullcheese")


def test_missing_argus_token_skips_argus_but_still_does_the_rest():
    db = baseline()
    db["projects"] = [p for p in db["projects"] if p["id"] != "argus"]
    plan = sl.run(FakeClient(db), apply=True, call=chain())
    assert any(n == "Argus" for n, _ in plan["skipped"])
    assert by_id(db, "bullcheese") is not None and by_id(db, "faze")["category"] == "launchpad"


def test_refuses_when_an_address_has_no_code_or_the_chain_is_wrong():
    db = baseline(); before = repr(db)
    with pytest.raises(SystemExit):
        sl.run(FakeClient(db), apply=True, call=chain(no_code=[FAZE]))
    assert repr(db) == before                                      # nothing written
    with pytest.raises(RuntimeError, match="not Arc mainnet"):
        sl.validate_on_chain(sl.all_addresses(), chain({"chain": "0x1"}))
    with pytest.raises(RuntimeError, match="malformed"):
        sl.validate_on_chain(["0xnothex"], chain())
