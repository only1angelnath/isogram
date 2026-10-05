"""Pagination of load_contract_project_map (PostgREST 1000-row cap) - no network."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db


class _Query:
    def __init__(self, rows):
        self.rows, self.after, self.n = rows, None, None

    def select(self, *a): return self
    def gt(self, col, val): self.after = val; return self
    def order(self, *a): return self
    def limit(self, n): self.n = n; return self

    def execute(self):
        rows = [r for r in self.rows if self.after is None or r["id"] > self.after][: self.n]
        return type("R", (), {"data": rows})()


class _Client:
    def __init__(self, rows): self.rows = rows
    def table(self, name):
        assert name == "projects"
        return _Query(self.rows)


def test_load_contract_project_map_reads_past_the_1000_row_cap():
    rows = [{"id": f"p{i:05d}", "contracts": [f"0x{i:040x}"]} for i in range(2500)]
    mapping = db.load_contract_project_map(_Client(rows))
    assert len(mapping) == 2500
    assert mapping[f"0x{2499:040x}"] == "p02499"


def test_load_contract_project_map_exact_page_boundary_and_empty():
    rows = [{"id": f"p{i:05d}", "contracts": [f"0x{i:040x}"]} for i in range(1000)]
    assert len(db.load_contract_project_map(_Client(rows))) == 1000
    assert db.load_contract_project_map(_Client([])) == {}
