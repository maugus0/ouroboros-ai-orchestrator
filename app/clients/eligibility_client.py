"""HTTP client for the Eligibility Engine agent service."""

from typing import Any

from app.clients.base_client import BaseAgentClient
from app.config import settings


class EligibilityClient(BaseAgentClient):
    base_url = settings.ELIGIBILITY_SERVICE_URL
    agent_name = "eligibility_engine"

    async def check_eligibility(
        self,
        evaluation: dict[str, Any],
        trace_id: str | None = None,
    ) -> dict:
        """POST /evaluate with keys: user_id, profile, programs, scholarships."""
        return await self._post("/evaluate", evaluation, trace_id=trace_id)
