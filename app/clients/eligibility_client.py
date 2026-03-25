"""HTTP client for the Eligibility Engine agent service."""

from app.clients.base_client import BaseAgentClient
from app.config import settings


class EligibilityClient(BaseAgentClient):
    base_url = settings.ELIGIBILITY_SERVICE_URL
    agent_name = "eligibility_engine"

    async def check_eligibility(
        self, user_id: str, profile: dict, programs: list, scholarships: list, trace_id: str | None = None
    ) -> dict:
        return await self._post(
            "/evaluate",
            {"user_id": user_id, "profile": profile, "programs": programs, "scholarships": scholarships},
            trace_id=trace_id,
        )
