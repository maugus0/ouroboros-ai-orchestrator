"""Reusable outbound HTTP client for downstream agent services."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class AgentClientError(RuntimeError):
    """Normalized downstream-call failure."""

    service_name: str
    message: str
    status_code: Optional[int] = None
    response_text: Optional[str] = None

    def __str__(self) -> str:
        return self.message


class AgentClient:
    """Thin wrapper around httpx with bounded retries and standard headers."""

    def __init__(
        self,
        base_url: str,
        service_name: str,
        timeout_seconds: float = 30.0,
        retries: int = 2,
        backoff_factor: float = 1.0,
        default_headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_name = service_name
        self.timeout_seconds = timeout_seconds
        self.retries = max(0, retries)
        self.backoff_factor = max(0.0, backoff_factor)
        self.default_headers = dict(default_headers or {})

    def _build_headers(
        self,
        *,
        trace_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> dict[str, str]:
        headers = {**self.default_headers}
        if authorization:
            headers["Authorization"] = authorization
        if trace_id:
            headers["X-Trace-ID"] = trace_id
        if user_id:
            headers["X-User-ID"] = user_id
        if session_id:
            headers["X-Session-ID"] = session_id
        if extra_headers:
            headers.update(extra_headers)
        return headers

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[dict[str, Any]] = None,
        params: Optional[Mapping[str, Any]] = None,
        trace_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> Any:
        headers = self._build_headers(
            trace_id=trace_id,
            user_id=user_id,
            session_id=session_id,
            authorization=authorization,
            extra_headers=extra_headers,
        )
        url = f"{self.base_url}{path}"

        last_error: Optional[Exception] = None
        attempts = self.retries + 1

        for attempt in range(1, attempts + 1):
            logger.info(
                "agent_request_started",
                service_name=self.service_name,
                method=method.upper(),
                url=url,
                attempt=attempt,
                max_attempts=attempts,
            )
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.request(
                        method=method.upper(),
                        url=url,
                        json=json,
                        params=params,
                        headers=headers,
                    )
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        message=f"{self.service_name} returned {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                logger.info(
                    "agent_request_succeeded",
                    service_name=self.service_name,
                    method=method.upper(),
                    url=url,
                    status_code=response.status_code,
                    attempt=attempt,
                )
                if not response.content:
                    return None
                return response.json()
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                response_text = getattr(getattr(exc, "response", None), "text", None)
                logger.warning(
                    "agent_request_failed",
                    service_name=self.service_name,
                    method=method.upper(),
                    url=url,
                    attempt=attempt,
                    max_attempts=attempts,
                    status_code=status_code,
                    error=str(exc),
                )
                if attempt >= attempts:
                    raise AgentClientError(
                        service_name=self.service_name,
                        message=f"{self.service_name} request failed",
                        status_code=status_code,
                        response_text=response_text,
                    ) from exc
                await asyncio.sleep(self.backoff_factor * attempt)

        raise AgentClientError(
            service_name=self.service_name, message=f"{self.service_name} request failed"
        ) from last_error
