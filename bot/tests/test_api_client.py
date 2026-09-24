"""
Tests for api_client.py. Uses httpx.MockTransport to simulate the Isogram
API's responses — no real network call, no live server required.
"""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api_client import ApiError, get_gas_top, get_score, get_tvl_top


def _client_with(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_get_score_success():
    def handler(request):
        assert request.url.path == "/scores/isogram"
        return httpx.Response(200, json={"id": "isogram", "score": 0.8})

    async with _client_with(handler) as client:
        data = await get_score(client, "isogram")
    assert data["score"] == 0.8


@pytest.mark.asyncio
async def test_get_score_not_found_returns_none():
    def handler(request):
        return httpx.Response(404, json={"detail": "not found"})

    async with _client_with(handler) as client:
        data = await get_score(client, "does-not-exist")
    assert data is None


@pytest.mark.asyncio
async def test_get_score_server_error_raises_api_error():
    def handler(request):
        return httpx.Response(500, json={"detail": "boom"})

    async with _client_with(handler) as client:
        with pytest.raises(ApiError):
            await get_score(client, "isogram")


@pytest.mark.asyncio
async def test_get_gas_top_passes_limit_query_param():
    def handler(request):
        assert request.url.path == "/gas/top"
        assert request.url.params["limit"] == "5"
        return httpx.Response(200, json=[{"id": "a", "usdc_gas_7d": 1.0}])

    async with _client_with(handler) as client:
        entries = await get_gas_top(client, 5)
    assert len(entries) == 1


@pytest.mark.asyncio
async def test_get_tvl_top_empty_response():
    def handler(request):
        return httpx.Response(200, json=[])

    async with _client_with(handler) as client:
        entries = await get_tvl_top(client, 10)
    assert entries == []


@pytest.mark.asyncio
async def test_network_failure_raises_api_error():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    async with _client_with(handler) as client:
        with pytest.raises(ApiError):
            await get_score(client, "isogram")


@pytest.mark.asyncio
async def test_cold_start_502_retries_then_succeeds(monkeypatch):
    import api_client

    monkeypatch.setattr(api_client, "COLD_START_RETRY_DELAYS_SECONDS", [0, 0, 0])

    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        if calls["count"] < 3:
            return httpx.Response(502)
        return httpx.Response(200, json={"id": "isogram", "score": 0.8})

    async with _client_with(handler) as client:
        data = await get_score(client, "isogram")

    assert data["score"] == 0.8
    assert calls["count"] == 3


@pytest.mark.asyncio
async def test_cold_start_502_exhausts_retries_raises_api_error(monkeypatch):
    import api_client

    monkeypatch.setattr(api_client, "COLD_START_RETRY_DELAYS_SECONDS", [0, 0])

    def handler(request):
        return httpx.Response(502)

    async with _client_with(handler) as client:
        with pytest.raises(ApiError, match="cold-starting"):
            await get_score(client, "isogram")


@pytest.mark.asyncio
async def test_404_does_not_trigger_cold_start_retries(monkeypatch):
    import api_client

    monkeypatch.setattr(api_client, "COLD_START_RETRY_DELAYS_SECONDS", [999])  # would hang the test if hit

    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        return httpx.Response(404)

    async with _client_with(handler) as client:
        data = await get_score(client, "does-not-exist")

    assert data is None
    assert calls["count"] == 1  # no retry loop entered for a real 404