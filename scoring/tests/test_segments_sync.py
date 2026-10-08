"""
scoring/segments.py and api/aggregate.py each carry the category -> segment table (they are
separate deployables). If they drift, the dashboard would show a score the scoring job never
computed (or the reverse). Skipped only when the api/ directory is not present (a scoring-only
checkout).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import segments

API_AGGREGATE = Path(__file__).resolve().parents[2] / "api" / "aggregate.py"


@pytest.mark.skipif(not API_AGGREGATE.exists(), reason="api/ not checked out next to scoring/")
def test_segment_tables_are_identical():
    spec = importlib.util.spec_from_file_location("api_aggregate_for_sync_test", API_AGGREGATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.SEGMENT_BY_CATEGORY == segments.SEGMENT_BY_CATEGORY


def test_only_defi_is_scored_and_gets_tvl():
    assert segments.SCORED_SEGMENTS == {"defi"} and segments.TVL_SEGMENTS == {"defi"}
    assert segments.segment_for("DEX") == "defi" and segments.segment_for(None) == "other"
    assert segments.segment_for("something-new") == "other"
