"""HTTP client for the Scholarship Discovery agent service."""

from app.clients.base_client import BaseAgentClient
from app.config import settings


class ScholarshipDiscoveryClient(BaseAgentClient):
    base_url = settings.SCHOLARSHIP_DISCOVERY_SERVICE_URL
    agent_name = "scholarship_discovery"

    async def discover(
        self, user_id: str, profile: dict, programs: list | None = None, trace_id: str | None = None
    ) -> dict:
        payload = {"user_id": user_id, "profile": profile}
        if programs:
            payload["programs"] = programs
        return await self._post("/discover", payload, trace_id=trace_id)
