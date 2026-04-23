"""HTTP client for calling the Eligibility Engine service."""

from dataclasses import dataclass
from typing import Any, Optional

import httpx
from fastapi import HTTPException, status

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class EligibilityRequestOptions:
    """Normalized request payload/options passed into the generic HTTP helper."""

    json_body: Optional[dict[str, Any]] = None
    params: Optional[dict[str, Any]] = None
    trace_id: Optional[str] = None


class EligibilityClient:
    """Thin HTTP client for the downstream eligibility-engine service."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        service_token: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> None:
        self.base_url = (base_url or settings.ELIGIBILITY_SERVICE_URL).rstrip("/")
        self.service_token = service_token or settings.X_SERVICE_TOKEN
        self.timeout = timeout or settings.AGENT_CALL_TIMEOUT

    def _build_headers(self, trace_id: Optional[str] = None) -> dict[str, str]:
        headers = {"X-Service-Token": self.service_token}
        if trace_id:
            headers["X-Trace-ID"] = trace_id
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        options: Optional[EligibilityRequestOptions] = None,
    ) -> dict[str, Any]:
        options = options or EligibilityRequestOptions()
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    json=options.json_body,
                    params=options.params,
                    headers=self._build_headers(options.trace_id),
                )
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as exc:
            logger.warning("eligibility_request_timeout", method=method, url=url)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Eligibility service timed out",
            ) from exc
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "eligibility_request_http_error",
                method=method,
                url=url,
                status_code=exc.response.status_code,
                response=exc.response.text,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Eligibility service returned HTTP {exc.response.status_code}",
            ) from exc
        except httpx.HTTPError as exc:
            logger.error("eligibility_request_transport_error", method=method, url=url, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Eligibility service unavailable",
            ) from exc

    async def evaluate(self, payload: dict[str, Any], trace_id: Optional[str] = None) -> dict[str, Any]:
        """Proxy a matching/evaluate request to the eligibility service."""
        return await self._request(
            "POST",
            "/matching/evaluate",
            EligibilityRequestOptions(json_body=payload, trace_id=trace_id),
        )

    async def get_results(
        self,
        user_id: str,
        query_params: Optional[dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Fetch paginated match results for the authenticated user."""
        params = {"page": 1, "page_size": 20, **(query_params or {})}
        if params.get("entity_type") is None:
            params.pop("entity_type", None)
        return await self._request(
            "GET",
            f"/matching/results/{user_id}",
            EligibilityRequestOptions(params=params, trace_id=trace_id),
        )

    async def get_result_detail(self, match_id: str, trace_id: Optional[str] = None) -> dict[str, Any]:
        """Fetch a single match result by ID."""
        return await self._request(
            "GET",
            f"/matching/results/detail/{match_id}",
            EligibilityRequestOptions(trace_id=trace_id),
        )

    async def get_attribution_report(self, match_id: str, trace_id: Optional[str] = None) -> dict[str, Any]:
        """Fetch an attribution report for a match result."""
        return await self._request(
            "GET",
            f"/attribution/report/{match_id}",
            EligibilityRequestOptions(trace_id=trace_id),
        )
