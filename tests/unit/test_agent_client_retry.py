"""Unit tests for base AgentClient retry behavior."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.clients.agent_client import AgentClient, AgentClientError


class _FakeAsyncClient:
    def __init__(self, request_handler: Callable[..., Any]) -> None:
        self._request_handler = request_handler

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        return None

    async def request(self, *args, **kwargs):
        return await self._request_handler(*args, **kwargs)


class _TestAgentClient(AgentClient):
    def __init__(self, *args: Any, request_handler: Callable[..., Any], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._request_handler = request_handler

    def _create_http_client(self) -> _FakeAsyncClient:
        return _FakeAsyncClient(self._request_handler)


@pytest.mark.asyncio
async def test_agent_client_retries_with_exponential_backoff():
    attempts = 0
    sleep_calls: list[float] = []

    async def _sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    async def _request_handler(*, method, url, json=None, params=None, headers=None):
        del json, params, headers
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ReadTimeout("timed out", request=httpx.Request(method, url))
        return httpx.Response(200, request=httpx.Request(method, url), json={"ok": True})

    client = _TestAgentClient(
        base_url="http://agent.test",
        service_name="agent-test",
        retries=2,
        backoff_factor=1.0,
        sleep_func=_sleep,
        request_handler=_request_handler,
    )

    payload = await client.request("GET", "/health")

    assert payload == {"ok": True}
    assert attempts == 3
    assert sleep_calls == [1.0, 2.0]


@pytest.mark.asyncio
async def test_agent_client_raises_after_exhausted_retries():
    attempts = 0

    async def _request_handler(*, method, url, json=None, params=None, headers=None):
        del json, params, headers
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, request=httpx.Request(method, url), text="downstream error")

    client = _TestAgentClient(
        base_url="http://agent.test",
        service_name="agent-test",
        retries=2,
        backoff_factor=1.0,
        sleep_func=lambda _seconds: _noop(),
        request_handler=_request_handler,
    )

    with pytest.raises(AgentClientError) as exc_info:
        await client.request("GET", "/health")

    assert attempts == 3
    assert exc_info.value.status_code == 503


async def _noop() -> None:
    return None
