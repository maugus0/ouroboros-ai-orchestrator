"""HTTP client for the Program Discovery agent service."""

from app.clients.base_client import BaseAgentClient
from app.config import settings


class ProgramDiscoveryClient(BaseAgentClient):
    base_url = settings.PROGRAM_DISCOVERY_SERVICE_URL
    agent_name = "program_discovery"

    async def discover(self, user_id: str, profile: dict, trace_id: str | None = None) -> dict:
        return await self._post("/discover", {"user_id": user_id, "profile": profile}, trace_id=trace_id)
