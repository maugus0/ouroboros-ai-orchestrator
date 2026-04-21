"""Client for the program-discovery service."""

from typing import Any, Optional

from app.clients.agent_client import AgentClient
from app.config import settings
from app.security.internal_token_issuer import InternalTokenIssuer


class ProgramDiscoveryClient(AgentClient):
    """HTTP client for program-discovery operations.

    Provides access to all PDA endpoints:
    - /chat/ask: LLM-powered Q&A about programs (primary integration point)
    - /chat/extract-intent: Extract search filters from natural language
    - /programs/*: Program search, ranking, and details
    - /institutions/*: Institution search, rankings, and details
    """

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

    # ─────────────────────────────────────────────────────────────────────────
    # Chat / LLM Endpoints (Primary Integration)
    # ─────────────────────────────────────────────────────────────────────────

    async def ask_question(
        self,
        question: str,
        *,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 10,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """POST /chat/ask — LLM-powered Q&A about programs.

        The primary integration point. Forwards a natural language question
        to PDA's LLM-powered endpoint which uses OpenAI/Anthropic with its
        database of institutions and programs to generate an answer.

        Returns: {"answer": "...", "programs": [...], "sources": [...]}
        """
        payload: dict[str, Any] = {"question": question, "limit": limit}
        if filters:
            payload["filters"] = filters
        return await self.request(
            "POST",
            "/chat/ask",
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

    async def extract_intent(
        self,
        text: str,
        *,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """POST /chat/extract-intent — Extract search filters from natural language.

        Returns: {"field": "...", "degree_type": "...", "country": "...", ...}
        """
        return await self.request(
            "POST",
            "/chat/extract-intent",
            json={"text": text},
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

    # ─────────────────────────────────────────────────────────────────────────
    # Program Endpoints
    # ─────────────────────────────────────────────────────────────────────────

    async def search_programs(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        *,
        field: Optional[str] = None,
        degree_type: Optional[str] = None,
        country: Optional[str] = None,
        institution_name: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /programs — Structured program search with filters."""
        params = {
            k: v
            for k, v in {
                "field": field,
                "degree_type": degree_type,
                "country": country,
                "institution_name": institution_name,
                "page": page,
                "page_size": page_size,
            }.items()
            if v is not None
        }
        return await self.request(
            "GET",
            "/programs",
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

    async def rank_programs(
        self,
        *,
        student_profile: dict[str, Any],
        filters: Optional[dict[str, Any]] = None,
        limit: int = 10,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """POST /programs/rank — Rank programs using weighted algorithm against a profile."""
        payload: dict[str, Any] = {
            "student_profile": student_profile,
            "limit": limit,
        }
        if filters:
            payload["filters"] = filters
        return await self.request(
            "POST",
            "/programs/rank",
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

    async def get_program_detail(
        self,
        program_id: str,
        *,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /programs/{program_id} — Get program details by ID."""
        return await self.request(
            "GET",
            f"/programs/{program_id}",
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

    async def get_program_requirements(
        self,
        program_id: str,
        *,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /programs/{program_id}/requirements — Get program admission requirements."""
        return await self.request(
            "GET",
            f"/programs/{program_id}/requirements",
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

    async def list_fields(
        self,
        *,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /programs/fields — List all available fields of study."""
        return await self.request(
            "GET",
            "/programs/fields",
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

    async def list_field_categories(
        self,
        *,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /programs/field-categories — List field categories."""
        return await self.request(
            "GET",
            "/programs/field-categories",
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

    # ─────────────────────────────────────────────────────────────────────────
    # Institution Endpoints
    # ─────────────────────────────────────────────────────────────────────────

    async def search_institutions(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        *,
        country: Optional[str] = None,
        name: Optional[str] = None,
        region: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /institutions — Search institutions with filters."""
        params = {
            k: v
            for k, v in {
                "country": country,
                "name": name,
                "region": region,
                "page": page,
                "page_size": page_size,
            }.items()
            if v is not None
        }
        return await self.request(
            "GET",
            "/institutions",
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

    async def get_institution_detail(
        self,
        institution_id: str,
        *,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /institutions/{institution_id} — Get institution details by ID."""
        return await self.request(
            "GET",
            f"/institutions/{institution_id}",
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

    async def get_institution_rankings(
        self,
        institution_id: str,
        *,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /institutions/{institution_id}/rankings — Get QS World Rankings for institution."""
        return await self.request(
            "GET",
            f"/institutions/{institution_id}/rankings",
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

    async def list_countries(
        self,
        *,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /institutions/countries — List all countries with institutions."""
        return await self.request(
            "GET",
            "/institutions/countries",
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
