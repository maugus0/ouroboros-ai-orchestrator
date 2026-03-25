"""
Base HTTP client for calling agent microservices.
Uses httpx for async HTTP and tenacity for retry logic.
"""

from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.core.logging import get_logger
from app.utils.exceptions import AgentCallError

logger = get_logger(__name__)


class BaseAgentClient:
    """
    Shared HTTP client behaviour for every agent service.

    Sub-classes set ``base_url`` and ``agent_name``, then call
    ``self._get()`` / ``self._post()`` for individual endpoints.
    """

    base_url: str
    agent_name: str

    def _headers(self, trace_id: str | None = None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Service-Token": settings.X_SERVICE_TOKEN,
        }
        if trace_id:
            headers["X-Trace-ID"] = trace_id
        return headers

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _post(self, path: str, payload: dict[str, Any], trace_id: str | None = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=settings.AGENT_CALL_TIMEOUT) as client:
                resp = await client.post(url, json=payload, headers=self._headers(trace_id))
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error("agent_http_error", agent=self.agent_name, url=url, status=exc.response.status_code)
            raise AgentCallError(self.agent_name, f"HTTP {exc.response.status_code}")
        except httpx.RequestError as exc:
            logger.error("agent_request_error", agent=self.agent_name, url=url, error=str(exc))
            raise AgentCallError(self.agent_name, str(exc))

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _get(self, path: str, params: dict | None = None, trace_id: str | None = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=settings.AGENT_CALL_TIMEOUT) as client:
                resp = await client.get(url, params=params, headers=self._headers(trace_id))
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error("agent_http_error", agent=self.agent_name, url=url, status=exc.response.status_code)
            raise AgentCallError(self.agent_name, f"HTTP {exc.response.status_code}")
        except httpx.RequestError as exc:
            logger.error("agent_request_error", agent=self.agent_name, url=url, error=str(exc))
            raise AgentCallError(self.agent_name, str(exc))
