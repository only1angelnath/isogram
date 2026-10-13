"""Shared fixtures. Rate-limit counters are process-wide, so reset them around every test; otherwise the
suite's own requests (all from one fake client address) would eat into each other's budget."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _fresh_access_state():
    import access
    import routes.keys as keys_route

    access.reset_all()
    keys_route.reset_all()
    yield
    access.reset_all()
    keys_route.reset_all()
