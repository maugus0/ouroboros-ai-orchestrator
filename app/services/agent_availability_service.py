"""Service availability checks for downstream orchestrator targets."""

from __future__ import annotations

from typing import Optional

import httpx

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class AgentAvailabilityService:
    """Performs best-effort health checks for mapped downstream agents."""

    _AGENT_BASE_URL_MAP = {
        "student-profile": settings.STUDENT_PROFILE_SERVICE_URL,
        "program-discovery": settings.PROGRAM_DISCOVERY_SERVICE_URL,
        "scholarship-discovery": settings.SCHOLARSHIP_DISCOVERY_SERVICE_URL,
        "eligibility-engine": settings.ELIGIBILITY_SERVICE_URL,
        "application-support": settings.APPLICATION_SUPPORT_SERVICE_URL,
    }

    def resolve_base_url(self, agent_name: Optional[str]) -> Optional[str]:
        if not agent_name:
            return None
        return self._AGENT_BASE_URL_MAP.get(agent_name.strip().lower())

    async def is_agent_available(self, agent_name: Optional[str]) -> bool:
        """Return true when mapped agent health endpoint responds OK."""
        base_url = self.resolve_base_url(agent_name)
        if not base_url:
            return False

        timeout_seconds = min(float(settings.AGENT_CALL_TIMEOUT), 3.0)
        health_url = f"{base_url.rstrip('/')}/health"
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.get(health_url)
            if response.status_code < 400:
                return True

            logger.warning(
                "agent_health_unhealthy_status",
                agent_name=agent_name,
                status_code=response.status_code,
                health_url=health_url,
            )
            return False
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "agent_health_check_failed",
                agent_name=agent_name,
                health_url=health_url,
                error=str(exc),
            )
            return False
