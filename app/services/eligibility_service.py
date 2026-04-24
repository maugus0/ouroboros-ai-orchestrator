"""Service layer for orchestrating calls to the Eligibility Engine."""

from dataclasses import dataclass
from typing import Any, Optional

from fastapi import HTTPException, status

from app.clients.agent_client import AgentClientError
from app.clients.eligibility_client import EligibilityClient
from app.clients.program_discovery_client import ProgramDiscoveryClient
from app.clients.scholarship_discovery_client import ScholarshipDiscoveryClient
from app.clients.student_profile_client import StudentProfileClient
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class EligibilityEvaluationInput:
    """Normalized evaluation payload forwarded to the downstream service."""

    user_id: str
    entity_type: str
    entity_id: str
    user_profile: Optional[dict[str, Any]] = None
    entity_data: Optional[dict[str, Any]] = None
    include_attribution: bool = True


@dataclass(frozen=True)
class EligibilityResultsQuery:
    """Pagination and filtering options for result-list lookups."""

    user_id: str
    entity_type: Optional[str] = None
    page: int = 1
    page_size: int = 20


class EligibilityService:
    """Business-layer wrapper around the downstream eligibility client."""

    def __init__(
        self,
        client: Optional[EligibilityClient] = None,
        student_profile_client: Optional[StudentProfileClient] = None,
        program_discovery_client: Optional[ProgramDiscoveryClient] = None,
        scholarship_discovery_client: Optional[ScholarshipDiscoveryClient] = None,
    ) -> None:
        self.client = client or EligibilityClient()
        self.student_profile_client = student_profile_client or StudentProfileClient()
        self.program_discovery_client = program_discovery_client or ProgramDiscoveryClient()
        self.scholarship_discovery_client = scholarship_discovery_client or ScholarshipDiscoveryClient()

    async def evaluate(
        self,
        request: EligibilityEvaluationInput,
        trace_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Evaluate a user against a program or scholarship."""
        user_profile = await self._hydrate_user_profile(
            user_id=request.user_id,
            trace_id=trace_id,
        )
        entity_data = await self._hydrate_entity_data(
            user_id=request.user_id,
            entity_type=request.entity_type,
            entity_id=request.entity_id,
            trace_id=trace_id,
        )

        payload = {
            "user_id": request.user_id,
            "entity_type": request.entity_type,
            "entity_id": request.entity_id,
            "user_profile": user_profile,
            "entity_data": entity_data,
            "include_attribution": request.include_attribution,
        }
        logger.info(
            "eligibility_evaluate_requested",
            user_id=request.user_id,
            entity_type=request.entity_type,
            entity_id=request.entity_id,
        )
        return await self.client.evaluate(payload, trace_id=trace_id)

    async def _hydrate_user_profile(
        self,
        *,
        user_id: str,
        trace_id: Optional[str],
    ) -> dict[str, Any]:
        try:
            status_response = await self.student_profile_client.get_profile_status(
                user_id,
                intent="eligibility_check",
                trace_id=trace_id,
            )
            profile_status = self._unwrap_response_data(status_response)
            profile_id = profile_status.get("profile_id")
            if not profile_id:
                raise HTTPException(
                    status_code=status.HTTP_424_FAILED_DEPENDENCY,
                    detail="Student profile is required before eligibility can be evaluated.",
                )

            profile_response = await self.student_profile_client.get_profile(
                profile_id,
                user_id=user_id,
                trace_id=trace_id,
            )
        except AgentClientError as exc:
            logger.warning("eligibility_profile_hydration_failed", user_id=user_id, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to fetch student profile for eligibility evaluation.",
            ) from exc

        profile = self._unwrap_response_data(profile_response)
        normalized_profile = self._normalize_student_profile(profile)
        if not normalized_profile:
            raise HTTPException(
                status_code=status.HTTP_424_FAILED_DEPENDENCY,
                detail="Student profile is empty and cannot be used for eligibility evaluation.",
            )
        return normalized_profile

    async def _hydrate_entity_data(
        self,
        *,
        user_id: str,
        entity_type: str,
        entity_id: str,
        trace_id: Optional[str],
    ) -> dict[str, Any]:
        try:
            if entity_type == "program":
                program_response = await self.program_discovery_client.get_program_detail(
                    entity_id,
                    user_id=user_id,
                    trace_id=trace_id,
                )
                return self._normalize_program_data(program_response)

            if entity_type == "scholarship":
                scholarship_response = await self.scholarship_discovery_client.get_scholarship_detail(
                    entity_id,
                    user_id=user_id,
                    trace_id=trace_id,
                )
                return self._normalize_scholarship_data(scholarship_response)
        except AgentClientError as exc:
            logger.warning(
                "eligibility_entity_hydration_failed",
                user_id=user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Unable to fetch {entity_type} details for eligibility evaluation.",
            ) from exc

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported eligibility entity_type '{entity_type}'.",
        )

    @staticmethod
    def _unwrap_response_data(response: dict[str, Any]) -> dict[str, Any]:
        data = response.get("data") if isinstance(response, dict) else None
        if isinstance(data, dict):
            return data
        return response if isinstance(response, dict) else {}

    @classmethod
    def _normalize_student_profile(cls, profile: dict[str, Any]) -> dict[str, Any]:
        profile_json = profile.get("profile_json") if isinstance(profile.get("profile_json"), dict) else {}
        target_country = profile_json.get("target_country") or profile_json.get("target_study_country")
        raw_gpa_normalized = profile.get("gpa_normalized")
        gpa_normalized = cls._coerce_float(raw_gpa_normalized)
        if gpa_normalized is None:
            gpa = cls._coerce_float(profile.get("gpa"))
            gpa_scale = cls._coerce_float(profile.get("gpa_scale"))
            if gpa is not None and gpa_scale and gpa_scale > 0:
                gpa_normalized = round((gpa / gpa_scale) * 4.0, 2)

        normalized = {
            "gpa_normalized": gpa_normalized,
            "citizenship": profile.get("nationality"),
            "field_of_study": profile_json.get("field_of_study")
            or profile_json.get("intended_field_of_study")
            or profile_json.get("fieldOfStudy"),
            "degree_level": cls._coalesce_degree_level(
                profile.get("target_degree_level"),
                profile.get("current_degree_level"),
            ),
            "technical_skills": cls._normalize_string_list(
                profile_json.get("technical_skills") or profile_json.get("skills")
            ),
            "completed_courses": cls._normalize_string_list(
                profile_json.get("completed_courses") or profile_json.get("courses")
            ),
            "research_interests": cls._normalize_string_list(profile_json.get("research_interests")),
            "preferred_locations": cls._normalize_string_list(
                profile_json.get("preferred_locations") or target_country
            ),
            "budget_usd": cls._coerce_float(profile_json.get("budget_usd")),
            "activities": cls._normalize_string_list(profile_json.get("activities")),
            "achievements": cls._normalize_string_list(profile_json.get("achievements")),
            "strengths": cls._normalize_string_list(profile_json.get("strengths")),
            "tags": cls._normalize_string_list(profile_json.get("tags")),
        }
        return {key: value for key, value in normalized.items() if value not in (None, [], "")}

    @classmethod
    def _normalize_program_data(cls, response: dict[str, Any]) -> dict[str, Any]:
        program = cls._unwrap_response_data(response)
        requirements = program.get("requirements") if isinstance(program.get("requirements"), dict) else {}
        normalized = {
            **program,
            "minimum_gpa": cls._coerce_float(
                requirements.get("minimum_gpa") or requirements.get("gpa") or requirements.get("min_gpa")
            ),
            "keywords": cls._normalize_string_list(
                requirements.get("keywords")
                or requirements.get("preferred_skills")
                or [program.get("field"), program.get("field_category")]
            ),
            "prerequisites": cls._normalize_string_list(
                requirements.get("prerequisites") or requirements.get("required_courses") or requirements.get("courses")
            ),
            "location": program.get("institution_country"),
            "tuition_usd": cls._coerce_float(program.get("tuition_usd")),
        }
        return {key: value for key, value in normalized.items() if value not in (None, [], "")}

    @classmethod
    def _normalize_scholarship_data(cls, response: dict[str, Any]) -> dict[str, Any]:
        scholarship = cls._unwrap_response_data(response)
        eligibility_criteria = (
            scholarship.get("eligibility_criteria") if isinstance(scholarship.get("eligibility_criteria"), dict) else {}
        )
        normalized = {
            **scholarship,
            "minimum_gpa": cls._coerce_float(
                eligibility_criteria.get("minimum_gpa")
                or eligibility_criteria.get("gpa")
                or eligibility_criteria.get("min_gpa")
            ),
            "eligible_citizenships": cls._normalize_string_list(
                eligibility_criteria.get("eligible_citizenships")
                or eligibility_criteria.get("nationalities")
                or eligibility_criteria.get("citizenship")
            ),
            "eligible_fields_of_study": cls._normalize_string_list(
                eligibility_criteria.get("eligible_fields_of_study")
                or eligibility_criteria.get("fields_of_study")
                or eligibility_criteria.get("field_of_study")
            ),
            "required_degree_level": eligibility_criteria.get("required_degree_level")
            or eligibility_criteria.get("degree_level")
            or eligibility_criteria.get("degree_type"),
            "preferred_criteria": eligibility_criteria.get("preferred_criteria")
            or scholarship.get("preferred_criteria"),
            # SDA stores the award as `funding_amount`; eligibility-engine scorer reads `award_amount_usd`
            "award_amount_usd": cls._coerce_float(
                scholarship.get("funding_amount") or scholarship.get("award_amount_usd")
            ),
            "funding_amount": cls._coerce_float(scholarship.get("funding_amount")),
        }
        return {key: value for key, value in normalized.items() if value not in (None, [], "")}

    @staticmethod
    def _normalize_string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            items = value
        else:
            items = [value]
        normalized = [str(item).strip() for item in items if str(item).strip()]
        return normalized

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coalesce_degree_level(*values: Any) -> Optional[str]:
        for value in values:
            normalized = str(value or "").strip().lower()
            if normalized and normalized != "unknown":
                return normalized
        return None

    async def get_results(
        self,
        query: EligibilityResultsQuery,
        trace_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Fetch paginated match results for the authenticated user."""
        return await self.client.get_results(
            user_id=query.user_id,
            query_params={
                "entity_type": query.entity_type,
                "page": query.page,
                "page_size": query.page_size,
            },
            trace_id=trace_id,
        )

    async def get_result_detail(self, *, match_id: str, trace_id: Optional[str] = None) -> dict[str, Any]:
        """Fetch a single match result by ID."""
        return await self.client.get_result_detail(match_id, trace_id=trace_id)

    async def get_attribution_report(self, *, match_id: str, trace_id: Optional[str] = None) -> dict[str, Any]:
        """Fetch an attribution report by match ID."""
        return await self.client.get_attribution_report(match_id, trace_id=trace_id)
