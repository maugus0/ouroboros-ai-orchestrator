"""Integration tests for AgentClient with mocked HTTP transport."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.clients.agent_client import AgentClient, AgentClientError


class _TransportAgentClient(AgentClient):
    def __init__(self, *args: Any, transport: httpx.MockTransport, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._transport = transport

    def _create_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout_seconds, transport=self._transport)


@pytest.mark.asyncio
async def test_agent_client_success_with_mock_transport():
    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ok"
        return httpx.Response(200, json={"service": "ok"}, request=request)

    client = _TransportAgentClient(
        base_url="http://mock-agent.local",
        service_name="mock-agent",
        retries=2,
        backoff_factor=1.0,
        sleep_func=_noop_sleep,
        transport=httpx.MockTransport(_handler),
    )

    response = await client.request("GET", "/ok")

    assert response == {"service": "ok"}


@pytest.mark.asyncio
async def test_agent_client_retries_then_succeeds_for_5xx():
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(503, text="temporary failure", request=request)
        return httpx.Response(200, json={"status": "recovered"}, request=request)

    client = _TransportAgentClient(
        base_url="http://mock-agent.local",
        service_name="mock-agent",
        retries=2,
        backoff_factor=1.0,
        sleep_func=_noop_sleep,
        transport=httpx.MockTransport(_handler),
    )

    response = await client.request("POST", "/recover", json={"x": 1})

    assert call_count == 3
    assert response == {"status": "recovered"}


@pytest.mark.asyncio
async def test_agent_client_retries_timeout_then_raises():
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("upstream timeout", request=request)

    client = _TransportAgentClient(
        base_url="http://mock-agent.local",
        service_name="mock-agent",
        retries=2,
        backoff_factor=1.0,
        sleep_func=_noop_sleep,
        transport=httpx.MockTransport(_handler),
    )

    with pytest.raises(AgentClientError) as exc_info:
        await client.request("GET", "/timeout")

    assert call_count == 3
    assert "request failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_agent_client_exhausts_retries_for_5xx():
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="still failing", request=request)

    client = _TransportAgentClient(
        base_url="http://mock-agent.local",
        service_name="mock-agent",
        retries=2,
        backoff_factor=1.0,
        sleep_func=_noop_sleep,
        transport=httpx.MockTransport(_handler),
    )

    with pytest.raises(AgentClientError) as exc_info:
        await client.request("GET", "/always-fail")

    assert exc_info.value.status_code == 500


async def _noop_sleep(_seconds: float) -> None:
    return None
