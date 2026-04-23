"""Client for the scholarship-discovery service.

SDA is a sibling microservice to PDA, handling scholarship crawling, eligibility
filtering, and program-linking. Key architectural points:

- SDA does NOT call PDA directly; orchestrator passes program context via payloads
- SDA does NOT call SPA directly; orchestrator passes student profile in payloads
- program_id in scholarship_program_links is an opaque UUID from orchestrator
"""

from typing import Any, Optional

from app.clients.agent_client import AgentClient
from app.config import settings
from app.security.internal_token_issuer import InternalTokenIssuer


class ScholarshipDiscoveryClient(AgentClient):
    """HTTP client for scholarship-discovery operations.

    Provides access to all SDA endpoints:
    - /api/v1/scholarships/search: Search scholarships with eligibility filtering
    - /api/v1/scholarships/{id}: Get scholarship details
    - /api/v1/scholarships/by-program/{program_id}: Get scholarships linked to a program
    - /api/v1/scholarships/link: Create scholarship-program link
    - /api/v1/scholarships/crawl: Trigger crawl jobs
    - /health: Health check
    """

    def __init__(self, internal_token_issuer: Optional[InternalTokenIssuer] = None) -> None:
        super().__init__(
            base_url=settings.SCHOLARSHIP_DISCOVERY_SERVICE_URL,
            service_name="scholarship-discovery",
            timeout_seconds=float(settings.AGENT_CALL_TIMEOUT),
            retries=settings.AGENT_CALL_RETRIES,
            backoff_factor=settings.AGENT_CALL_BACKOFF_FACTOR,
        )
        self._internal_token_issuer = internal_token_issuer or InternalTokenIssuer()
        self._internal_service_name = "scholarship-discovery"

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

    # ─────────────────────────────────────────────────────────────────────────
    # Health Check
    # ─────────────────────────────────────────────────────────────────────────

    async def probe_health(
        self,
        *,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /health — Verify orchestrator can reach scholarship-discovery."""
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
    # Scholarship Search & Details
    # ─────────────────────────────────────────────────────────────────────────

    async def search_scholarships(
        self,
        user_id: str,
        *,
        student_profile: Optional[dict[str, Any]] = None,
        program_ids: Optional[list[str]] = None,
        provider: Optional[str] = None,
        max_results: int = 20,
        page: int = 1,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """POST /api/v1/scholarships/search — Search and filter scholarships.

        Args:
            user_id: Authenticated user ID
            student_profile: Optional student profile for eligibility filtering
                Expected shape: {gpa, gpa_scale, nationality, field_of_study,
                degree_type, language_test}
            program_ids: Optional list of program UUIDs to filter by linked programs
            provider: Optional filter by scholarship provider
            max_results: Max results per page (default 20, max 100)
            page: Page number (1-indexed)

        Returns: {success, data: [scholarships], total, page, page_size}
        """
        payload: dict[str, Any] = {
            "max_results": max_results,
            "page": page,
        }
        if student_profile:
            payload["student_profile"] = student_profile
        if program_ids:
            payload["program_ids"] = program_ids
        if provider:
            payload["provider"] = provider

        return await self.request(
            "POST",
            "/api/v1/scholarships/search",
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

    async def get_scholarship_detail(
        self,
        scholarship_id: str,
        *,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /api/v1/scholarships/{scholarship_id} — Get full scholarship details."""
        return await self.request(
            "GET",
            f"/api/v1/scholarships/{scholarship_id}",
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

    async def get_scholarships_by_program(
        self,
        program_id: str,
        *,
        min_confidence: Optional[float] = None,
        page: int = 1,
        limit: int = 20,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /api/v1/scholarships/by-program/{program_id} — Get scholarships linked to a program.

        Args:
            program_id: Program UUID (opaque ID from orchestrator/PDA)
            min_confidence: Minimum link confidence score (0.0-1.0)
            page: Page number (1-indexed)
            limit: Items per page (max 100)

        Returns: {success, data: [scholarships with link_confidence], total, page, page_size}
        """
        params: dict[str, Any] = {"page": page, "limit": limit}
        if min_confidence is not None:
            params["min_confidence"] = min_confidence

        return await self.request(
            "GET",
            f"/api/v1/scholarships/by-program/{program_id}",
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

    # ─────────────────────────────────────────────────────────────────────────
    # Scholarship-Program Linking
    # ─────────────────────────────────────────────────────────────────────────

    async def link_scholarship_to_program(
        self,
        scholarship_id: str,
        program_id: str,
        university_name: str,
        field: str,
        degree_type: str,
        *,
        country: Optional[str] = None,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """POST /api/v1/scholarships/link — Create/update a scholarship-program link.

        The orchestrator passes program metadata from PDA to SDA for the 4-dimension
        confidence scoring (university, field, degree, geography).

        Args:
            scholarship_id: Scholarship UUID
            program_id: Program UUID (from PDA via orchestrator)
            university_name: Institution name from PDA
            field: Field of study from PDA
            degree_type: Degree type (bachelor, master, phd)
            country: Optional country for geographic scoring

        Returns: {success, data: {link details} or None if below confidence threshold}
        """
        payload = {
            "scholarship_id": scholarship_id,
            "program_metadata": {
                "program_id": program_id,
                "university_name": university_name,
                "field": field,
                "degree_type": degree_type,
                "country": country,
            },
        }

        return await self.request(
            "POST",
            "/api/v1/scholarships/link",
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

    # ─────────────────────────────────────────────────────────────────────────
    # Crawl Management (Admin)
    # ─────────────────────────────────────────────────────────────────────────

    async def trigger_crawl(
        self,
        job_type: str,
        *,
        target_url: Optional[str] = None,
        target_source: Optional[str] = None,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """POST /api/v1/scholarships/crawl — Trigger a new crawl job.

        Args:
            job_type: 'on_demand' or 'batch'
            target_url: URL to crawl (required for on_demand)
            target_source: Source identifier (alternative to target_url)

        Returns: {success, data: {job details}, message}
        """
        payload: dict[str, Any] = {"job_type": job_type}
        if target_url:
            payload["target_url"] = target_url
        if target_source:
            payload["target_source"] = target_source

        return await self.request(
            "POST",
            "/api/v1/scholarships/crawl",
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

    async def get_crawl_status(
        self,
        job_id: str,
        *,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /api/v1/scholarships/crawl/{job_id} — Get crawl job status."""
        return await self.request(
            "GET",
            f"/api/v1/scholarships/crawl/{job_id}",
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

    async def list_crawl_jobs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: Optional[str] = None,
        user_id: str,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /api/v1/scholarships/crawl — List crawl jobs."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status

        return await self.request(
            "GET",
            "/api/v1/scholarships/crawl",
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
