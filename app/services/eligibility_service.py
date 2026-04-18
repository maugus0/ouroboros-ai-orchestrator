"""Service layer for orchestrating calls to the Eligibility Engine."""

from dataclasses import dataclass
from typing import Any, Optional

from app.clients.eligibility_client import EligibilityClient
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class EligibilityEvaluationInput:
    """Normalized evaluation payload forwarded to the downstream service."""

    user_id: str
    entity_type: str
    entity_id: str
    user_profile: dict[str, Any]
    entity_data: dict[str, Any]
    include_attribution: bool = True


@dataclass(frozen=True)
class EligibilityResultsQuery:
    """Pagination and filtering options for result-list lookups."""

    user_id: str
    entity_type: Optional[str] = None
    page: int = 1
    page_size: int = 20


class EligibilityService:
    """Business-layer wrapper around the downstream eligibility client."""

    def __init__(self, client: Optional[EligibilityClient] = None) -> None:
        self.client = client or EligibilityClient()

    async def evaluate(
        self,
        request: EligibilityEvaluationInput,
        trace_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Evaluate a user against a program or scholarship."""
        payload = {
            "user_id": request.user_id,
            "entity_type": request.entity_type,
            "entity_id": request.entity_id,
            "user_profile": request.user_profile,
            "entity_data": request.entity_data,
            "include_attribution": request.include_attribution,
        }
        logger.info(
            "eligibility_evaluate_requested",
            user_id=request.user_id,
            entity_type=request.entity_type,
            entity_id=request.entity_id,
        )
        return await self.client.evaluate(payload, trace_id=trace_id)

    async def get_results(
        self,
        query: EligibilityResultsQuery,
        trace_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Fetch paginated match results for the authenticated user."""
        return await self.client.get_results(
            user_id=query.user_id,
            query_params={
                "entity_type": query.entity_type,
                "page": query.page,
                "page_size": query.page_size,
            },
            trace_id=trace_id,
        )

    async def get_result_detail(self, *, match_id: str, trace_id: Optional[str] = None) -> dict[str, Any]:
        """Fetch a single match result by ID."""
        return await self.client.get_result_detail(match_id, trace_id=trace_id)

    async def get_attribution_report(self, *, match_id: str, trace_id: Optional[str] = None) -> dict[str, Any]:
        """Fetch an attribution report by match ID."""
        return await self.client.get_attribution_report(match_id, trace_id=trace_id)
