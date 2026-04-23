"""Unit tests for the downstream EligibilityClient."""

from typing import Any, Optional

import httpx
import pytest
from fastapi import HTTPException

from app.clients.eligibility_client import EligibilityClient


class _FakeResponse:
    """Small fake response object used to emulate httpx responses."""

    def __init__(self, *, status_code: int = 200, json_body: Optional[dict[str, Any]] = None, text: str = "") -> None:
        self.status_code = status_code
        self._json_body = json_body or {}
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://testserver")
            raise httpx.HTTPStatusError("downstream error", request=request, response=self)

    def json(self) -> dict[str, Any]:
        return self._json_body


class _FakeAsyncClient:
    """Context-manager stub that delegates request handling to a provided callback."""

    def __init__(self, request_handler):
        self._request_handler = request_handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def request(self, **kwargs):
        return await self._request_handler(**kwargs)


@pytest.mark.asyncio
async def test_client_forwards_headers_payload_and_params(monkeypatch):
    """Client should forward service token, trace ID, payload and params to downstream."""
    captured: dict[str, Any] = {}

    async def request_handler(**request_kwargs):
        captured.update(request_kwargs)
        return _FakeResponse(json_body={"success": True, "message": "OK", "data": {"items": []}})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda timeout: _FakeAsyncClient(request_handler),  # noqa: ARG005
    )

    client = EligibilityClient(base_url="http://eligibility", service_token="token-123", timeout=5)
    result = await client.get_results(
        user_id="user-1",
        query_params={"entity_type": "program", "page": 2, "page_size": 5},
        trace_id="trace-abc",
    )

    assert result["success"] is True
    assert captured["url"] == "http://eligibility/matching/results/user-1"
    assert captured["params"] == {"page": 2, "page_size": 5, "entity_type": "program"}
    assert captured["headers"] == {"X-Service-Token": "token-123", "X-Trace-ID": "trace-abc"}


@pytest.mark.asyncio
async def test_client_maps_timeout_to_504(monkeypatch):
    """Transport timeouts should become 504 errors for the orchestrator caller."""

    async def request_handler(**_kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda timeout: _FakeAsyncClient(request_handler),  # noqa: ARG005
    )

    client = EligibilityClient(base_url="http://eligibility", service_token="token-123", timeout=5)

    with pytest.raises(HTTPException) as exc_info:
        await client.evaluate({"user_id": "user-1"})

    assert exc_info.value.status_code == 504
    assert exc_info.value.detail == "Eligibility service timed out"


@pytest.mark.asyncio
async def test_client_maps_http_error_to_502(monkeypatch):
    """Downstream HTTP errors should surface as 502 to the upstream caller."""

    async def request_handler(**_kwargs):
        return _FakeResponse(status_code=403, text="forbidden")

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda timeout: _FakeAsyncClient(request_handler),  # noqa: ARG005
    )

    client = EligibilityClient(base_url="http://eligibility", service_token="token-123", timeout=5)

    with pytest.raises(HTTPException) as exc_info:
        await client.get_result_detail("match-1")

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Eligibility service returned HTTP 403"
