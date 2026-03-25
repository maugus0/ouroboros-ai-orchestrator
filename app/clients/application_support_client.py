"""HTTP client for the Application Support agent service."""

from app.clients.base_client import BaseAgentClient
from app.config import settings


class ApplicationSupportClient(BaseAgentClient):
    base_url = settings.APPLICATION_SUPPORT_SERVICE_URL
    agent_name = "application_support"

    async def generate_materials(self, user_id: str, profile: dict, matches: list, trace_id: str | None = None) -> dict:
        return await self._post(
            "/generate",
            {"user_id": user_id, "profile": profile, "matches": matches},
            trace_id=trace_id,
        )
