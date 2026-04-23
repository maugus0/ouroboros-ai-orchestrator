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
        student_profile: Optional[dict[str, Any]] = None,
        limit: int = 10,
        include_explainability: bool = True,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """POST /chat/ask — LLM-powered Q&A about programs.

        The primary integration point. Forwards a natural language question
        to PDA's LLM-powered endpoint which uses OpenAI/Anthropic with its
        database of institutions and programs to generate an answer.

        Args:
            question: The user's question about programs
            filters: Optional search filters (field, degree_type, country, etc.)
            student_profile: Optional student profile for personalized responses
                Expected shape: {gpa, nationality, target_degree_level, field_of_study,
                target_country, work_experience_years, research_interests, skills, test_scores}
            limit: Max programs to consider (default 10)
            include_explainability: Include agent_reasoning with ReAct trace (default True)

        Returns:
            {
                "answer": str,
                "programs_mentioned": list[str],
                "follow_up_suggestions": list[str],
                "confidence": float,
                "model": str,
                "provider": str,
                "agent_reasoning": {  # Optional, when include_explainability=True
                    "approach": str,
                    "decision_factors": list[str],
                    "ranking_breakdown": list[{program_id, program_name, university,
                        composite_score, rank, match_scores, evidence}],
                    "filters_applied": list[str],
                    "total_programs_evaluated": int,
                    "total_programs_recommended": int,
                    "confidence": float,
                    "model": str,
                    "provider": str,
                    "react_decision_trace": dict
                }
            }
        """
        payload: dict[str, Any] = {
            "question": question,
            "limit": limit,
            "include_explainability": include_explainability,
        }
        if filters:
            payload["filters"] = filters
        if student_profile:
            payload["student_profile"] = student_profile
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

        Returns: {"intent": "...", "filters": {...}, "entities": {...}}
        """
        return await self.request(
            "POST",
            "/chat/extract-intent",
            json={"message": text},
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
        query: Optional[str] = None,
        field: Optional[str] = None,
        degree_type: Optional[str] = None,
        country: Optional[str] = None,
        institution_id: Optional[str] = None,
        min_rank: Optional[int] = None,
        max_rank: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /programs — Structured program search with filters.

        Args:
            query: Search by program name or description
            field: Filter by field of study
            degree_type: Filter by degree type (bachelor, master, phd)
            country: Filter by country
            institution_id: Filter by institution UUID
            min_rank: Min university rank
            max_rank: Max university rank
            page: Page number (1-indexed)
            page_size: Items per page (max 100)
        """
        params = {
            k: v
            for k, v in {
                "query": query,
                "field": field,
                "degree_type": degree_type,
                "country": country,
                "institution_id": institution_id,
                "min_rank": min_rank,
                "max_rank": max_rank,
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
        target_field: str,
        target_degree: Optional[str] = None,
        country_preferences: Optional[list[str]] = None,
        max_tuition_usd: Optional[float] = None,
        deadline_cutoff: Optional[str] = None,
        limit: int = 10,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """POST /programs/rank — Rank programs against a profile."""
        payload: dict[str, Any] = {
            "student_profile": student_profile,
            "target_field": target_field,
            "limit": limit,
        }
        if target_degree:
            payload["target_degree"] = target_degree
        if country_preferences:
            payload["country_preferences"] = country_preferences
        if max_tuition_usd is not None:
            payload["max_tuition_usd"] = max_tuition_usd
        if deadline_cutoff:
            payload["deadline_cutoff"] = deadline_cutoff
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
        query: Optional[str] = None,
        country: Optional[str] = None,
        institution_type: Optional[str] = None,
        min_rank: Optional[int] = None,
        max_rank: Optional[int] = None,
        ranking_source: Optional[str] = None,
        ranking_year: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /institutions — Search institutions with filters.

        Args:
            query: Search by institution name
            country: Filter by country
            institution_type: Filter by type (public, private)
            min_rank: Minimum rank position
            max_rank: Maximum rank position
            ranking_source: Filter by ranking source (qs_world, etc.)
            ranking_year: Filter by ranking year
            page: Page number (1-indexed)
            page_size: Items per page (max 100)
        """
        params = {
            k: v
            for k, v in {
                "query": query,
                "country": country,
                "institution_type": institution_type,
                "min_rank": min_rank,
                "max_rank": max_rank,
                "ranking_source": ranking_source,
                "ranking_year": ranking_year,
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
