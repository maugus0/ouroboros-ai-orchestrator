"""HTTP client for the Student Profile agent service."""

from app.clients.base_client import BaseAgentClient
from app.config import settings


class StudentProfileClient(BaseAgentClient):
    base_url = settings.STUDENT_PROFILE_SERVICE_URL
    agent_name = "student_profile"

    async def parse_cv(self, user_id: str, cv_text: str | None = None, trace_id: str | None = None) -> dict:
        return await self._post("/parse", {"user_id": user_id, "cv_text": cv_text}, trace_id=trace_id)

    async def get_profile(self, user_id: str, trace_id: str | None = None) -> dict:
        return await self._get(f"/profiles/{user_id}", trace_id=trace_id)
