"""Service layer for orchestrating calls to the Eligibility Engine."""

from typing import Any, Optional

from app.clients.eligibility_client import EligibilityClient
from app.core.logging import get_logger

logger = get_logger(__name__)


class EligibilityService:
    """Business-layer wrapper around the downstream eligibility client."""

    def __init__(self, client: Optional[EligibilityClient] = None) -> None:
        self.client = client or EligibilityClient()

    async def evaluate(
        self,
        *,
        user_id: str,
        entity_type: str,
        entity_id: str,
        user_profile: dict[str, Any],
        entity_data: dict[str, Any],
        include_attribution: bool = True,
        trace_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Evaluate a user against a program or scholarship."""
        payload = {
            "user_id": user_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "user_profile": user_profile,
            "entity_data": entity_data,
            "include_attribution": include_attribution,
        }
        logger.info("eligibility_evaluate_requested", user_id=user_id, entity_type=entity_type, entity_id=entity_id)
        return await self.client.evaluate(payload, trace_id=trace_id)

    async def get_results(
        self,
        *,
        user_id: str,
        entity_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        trace_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Fetch paginated match results for the authenticated user."""
        return await self.client.get_results(
            user_id=user_id,
            entity_type=entity_type,
            page=page,
            page_size=page_size,
            trace_id=trace_id,
        )

    async def get_result_detail(self, *, match_id: str, trace_id: Optional[str] = None) -> dict[str, Any]:
        """Fetch a single match result by ID."""
        return await self.client.get_result_detail(match_id, trace_id=trace_id)

    async def get_attribution_report(self, *, match_id: str, trace_id: Optional[str] = None) -> dict[str, Any]:
        """Fetch an attribution report by match ID."""
        return await self.client.get_attribution_report(match_id, trace_id=trace_id)
