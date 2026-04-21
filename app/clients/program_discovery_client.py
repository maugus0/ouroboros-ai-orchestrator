"""Client for the program-discovery service."""

from typing import Any, Optional

from app.clients.agent_client import AgentClient
from app.config import settings
from app.security.internal_token_issuer import InternalTokenIssuer


class ProgramDiscoveryClient(AgentClient):
    """HTTP client for program-discovery operations."""

    def __init__(self, internal_token_issuer: Optional[InternalTokenIssuer] = None) -> None:
        super().__init__(
            base_url=settings.PROGRAM_DISCOVERY_SERVICE_URL,
            service_name="program-discovery",
            timeout_seconds=float(settings.AGENT_CALL_TIMEOUT),
            retries=settings.AGENT_CALL_RETRIES,
            backoff_factor=settings.AGENT_CALL_BACKOFF_FACTOR,
        )
        self._internal_token_issuer = internal_token_issuer or InternalTokenIssuer()
        self._internal_service_name = "program-discovery"

    def _resolve_authorization(
        self,
        *,
        authorization: Optional[str],
        user_id: str,
        session_id: Optional[str],
        trace_id: Optional[str],
    ) -> Optional[str]:
        if authorization:
            return authorization
        if not settings.INTERNAL_TOKEN_ENABLED:
            return None

        audience = self._internal_token_issuer.resolve_audience(self._internal_service_name)
        return self._internal_token_issuer.build_bearer_token(
            sub=user_id,
            aud=audience,
            sid=session_id,
            trace_id=trace_id,
        )

    async def probe_health(
        self,
        *,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """Best-effort probe call to verify orchestrator can reach program-discovery."""
        return await self.request(
            "GET",
            "/health",
            trace_id=trace_id,
            user_id=user_id,
            session_id=session_id,
            authorization=self._resolve_authorization(
                authorization=authorization,
                user_id=user_id,
                session_id=session_id,
                trace_id=trace_id,
            ),
        )
