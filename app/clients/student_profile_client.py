"""Client for the student-profile service."""

from typing import Any, Optional

from app.clients.agent_client import AgentClient
from app.config import settings
from app.security.internal_token_issuer import InternalTokenIssuer


class StudentProfileClient(AgentClient):
    """HTTP client for readiness and profile-status operations."""

    def __init__(self, internal_token_issuer: Optional[InternalTokenIssuer] = None) -> None:
        super().__init__(
            base_url=settings.STUDENT_PROFILE_SERVICE_URL,
            service_name="student-profile",
            timeout_seconds=float(settings.AGENT_CALL_TIMEOUT),
            retries=settings.AGENT_CALL_RETRIES,
            backoff_factor=settings.AGENT_CALL_BACKOFF_FACTOR,
        )
        self._internal_token_issuer = internal_token_issuer or InternalTokenIssuer()
        self._internal_service_name = "student-profile"

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

    async def get_profile_status(
        self,
        user_id: str,
        *,
        intent: Optional[str] = None,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """Fetch the readiness status for the given user."""
        params = {"intent": intent} if intent else None
        return await self.request(
            "GET",
            "/api/v1/profiles/status",
            params=params,
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

    async def get_profile_clarifications(
        self,
        profile_id: str,
        *,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """Fetch unresolved clarifications and the latest ReAct trace for a profile."""
        return await self.request(
            "GET",
            f"/api/v1/profiles/{profile_id}/clarifications",
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

    async def submit_profile_clarifications(
        self,
        profile_id: str,
        *,
        user_id: str,
        answers: list[dict[str, Any]],
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """Submit clarification answers for a profile and return refreshed queue/trace."""
        return await self.request(
            "POST",
            f"/api/v1/profiles/{profile_id}/clarifications",
            json={"answers": answers},
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

    async def sync_user_profile(
        self,
        user_id: str,
        payload: dict[str, Any],
        *,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """Upsert basic user fields into student profile service."""
        return await self.request(
            "POST",
            "/api/v1/profiles/sync-user",
            json={"user_id": user_id, **payload},
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

    async def collect_from_chat(
        self,
        user_id: str,
        fields: dict[str, Any],
        *,
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        extraction_candidates: Optional[dict[str, Any]] = None,
        pending_clarification_fields: Optional[list[str]] = None,
        correction_fields: Optional[list[str]] = None,
        telemetry_summary: Optional[dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """Persist profile fields extracted from chat and get refreshed readiness."""
        payload: dict[str, Any] = {
            "user_id": user_id,
            "fields": fields,
        }
        if chat_id:
            payload["chat_id"] = chat_id
        if message_id:
            payload["message_id"] = message_id
        if extraction_candidates:
            payload["extractions"] = extraction_candidates
        if pending_clarification_fields:
            payload["pending_clarification_fields"] = pending_clarification_fields
        if correction_fields:
            payload["correction_fields"] = correction_fields
        if telemetry_summary:
            payload["extraction_telemetry"] = telemetry_summary

        return await self.request(
            "POST",
            "/api/v1/profiles/collect-from-chat",
            json=payload,
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

    async def parse_document_upload(
        self,
        user_id: str,
        file_name: str,
        file_content_base64: str,
        *,
        intent: Optional[str] = None,
        document_type: str = "cv",
        target_degree_hint: Optional[str] = None,
        run_gap_analysis: bool = False,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """Forward a CV/transcript upload to the student-profile parser."""
        payload: dict[str, Any] = {
            "user_id": user_id,
            "file_name": file_name,
            "file_content_base64": file_content_base64,
            "intent": intent,
            "document_type": document_type,
            "run_gap_analysis": run_gap_analysis,
        }
        if target_degree_hint is not None:
            payload["target_degree_hint"] = target_degree_hint

        return await self.request(
            "POST",
            "/api/v1/profiles/parse",
            json=payload,
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
