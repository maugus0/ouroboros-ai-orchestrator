"""Profile readiness checks used by chat orchestration and workflow visibility."""

import re
import time
import uuid
from collections import OrderedDict
from typing import Any, Optional

import aiomysql
import pycountry
from fastapi import HTTPException, status

from app.clients.agent_client import AgentClientError
from app.clients.student_profile_client import StudentProfileClient
from app.core.database import get_pool
from app.core.logging import get_logger
from app.repositories.agent_call_log_repo import AgentCallLogRepository
from app.repositories.user_repo import UserRepository
from app.services.intent_registry_service import IntentRegistryService

logger = get_logger(__name__)

# --- Module-level constants for field validation (avoid per-call allocation) ---

_BLOCKED_FIELD_PREFIXES: tuple[str, ...] = (
    "i ",
    "my ",
    "we ",
    "looking ",
    "planning ",
    "want ",
    "need ",
    "study ",
)

_NON_ACADEMIC_DESCRIPTORS: frozenset[str] = frozenset(
    {
        "budget-friendly",
        "budget friendly",
        "affordable",
        "cheap",
        "expensive",
        "top",
        "best",
        "worst",
        "good",
        "bad",
        "ranked",
        "ranking",
        "prestigious",
        "elite",
        "famous",
        "popular",
        "new",
        "old",
        "large",
        "small",
        "online",
        "remote",
        "nearby",
        "local",
        "international",
        "global",
        "free",
    }
)

_DEGREE_KEYWORDS: frozenset[str] = frozenset(
    {
        "phd",
        "doctorate",
        "doctoral",
        "master",
        "masters",
        "msc",
        "m.sc",
        "ms",
        "mba",
        "bachelor",
        "bachelors",
        "bsc",
        "b.sc",
        "bs",
        "high school",
        "highschool",
        "undergraduate",
    }
)

_DEGREE_PHRASES: frozenset[str] = frozenset(
    {
        "master degree",
        "masters degree",
        "master's degree",
        "bachelor degree",
        "bachelors degree",
        "bachelor's degree",
        "phd degree",
        "doctoral degree",
        "doctorate degree",
        "undergraduate degree",
    }
)

_DEGREE_PHRASE_MAP: dict[str, str] = {
    "master degree": "master",
    "masters degree": "master",
    "master's degree": "master",
    "bachelor degree": "bachelor",
    "bachelors degree": "bachelor",
    "bachelor's degree": "bachelor",
    "phd degree": "phd",
    "doctoral degree": "phd",
    "doctorate degree": "phd",
    "undergraduate degree": "bachelor",
    "high school degree": "high_school",
}


def _lazy_student_profile_client() -> StudentProfileClient:
    return StudentProfileClient()


def _lazy_user_repo() -> UserRepository:
    return UserRepository(get_pool())


def _lazy_agent_call_log_repo() -> AgentCallLogRepository:
    return AgentCallLogRepository(get_pool())


def _lazy_intent_registry_service() -> IntentRegistryService:
    return IntentRegistryService()


class ProfileGateService:
    """Evaluate whether a user may proceed to non-profile agent flows."""

    _AUTO_PERSIST_CONFIDENCE_THRESHOLD = 0.85
    _READINESS_CACHE_TTL_SECONDS = 30
    _READINESS_CACHE_MAX_ENTRIES = 256
    _READINESS_CACHE: OrderedDict[tuple[str, str], tuple[float, dict[str, Any]]] = OrderedDict()

    _COUNTRY_ALIASES = {
        "usa": "United States",
        "u.s.": "United States",
        "u.s.a.": "United States",
        "united states": "United States",
        "uk": "United Kingdom",
        "u.k.": "United Kingdom",
        "united kingdom": "United Kingdom",
        "england": "United Kingdom",
    }

    _MONTH_ALIASES = {
        "jan": "January",
        "january": "January",
        "feb": "February",
        "february": "February",
        "mar": "March",
        "march": "March",
        "apr": "April",
        "april": "April",
        "may": "May",
        "jun": "June",
        "june": "June",
        "jul": "July",
        "july": "July",
        "aug": "August",
        "august": "August",
        "sep": "September",
        "sept": "September",
        "september": "September",
        "oct": "October",
        "october": "October",
        "nov": "November",
        "november": "November",
        "dec": "December",
        "december": "December",
    }

    def __init__(
        self,
        student_profile_client: Optional[StudentProfileClient] = None,
        user_repo: Optional[UserRepository] = None,
        agent_call_log_repo: Optional[AgentCallLogRepository] = None,
        intent_registry_service: Optional[IntentRegistryService] = None,
    ) -> None:
        self._student_profile_client = student_profile_client
        self._user_repo = user_repo
        self._agent_call_log_repo = agent_call_log_repo
        self._intent_registry_service = intent_registry_service

    @property
    def student_profile_client(self) -> StudentProfileClient:
        if self._student_profile_client is None:
            self._student_profile_client = _lazy_student_profile_client()
        return self._student_profile_client

    @property
    def user_repo(self) -> UserRepository:
        if self._user_repo is None:
            self._user_repo = _lazy_user_repo()
        return self._user_repo

    @property
    def agent_call_log_repo(self) -> Optional[AgentCallLogRepository]:
        if self._agent_call_log_repo is None:
            try:
                self._agent_call_log_repo = _lazy_agent_call_log_repo()
            except RuntimeError:
                return None
        return self._agent_call_log_repo

    @property
    def intent_registry_service(self) -> IntentRegistryService:
        if self._intent_registry_service is None:
            self._intent_registry_service = _lazy_intent_registry_service()
        return self._intent_registry_service

    async def get_user_readiness(
        self,
        user_id: str,
        *,
        intent: Optional[str] = None,
        chat_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
        retry_of_log_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return a deterministic readiness snapshot for the current user."""
        normalized_intent = intent or "profile_completion"
        cache_key = self._readiness_cache_key(user_id, normalized_intent)
        self._prune_readiness_cache()
        cached = self._get_cached_readiness(cache_key)
        if cached is not None:
            logger.info("profile_readiness_cache_hit", user_id=user_id, intent=normalized_intent)
            return cached

        started_at = time.perf_counter()
        try:
            payload = await self.student_profile_client.get_profile_status(user_id=user_id, intent=normalized_intent)
            await self._record_agent_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="get_profile_status",
                request_method="GET",
                request_path="/api/v1/profiles/status",
                call_status="success",
                response_payload=payload if isinstance(payload, dict) else None,
                latency_ms=self._elapsed_ms(started_at),
                retry_of_log_id=retry_of_log_id,
            )
        except AgentClientError as exc:
            await self._record_agent_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="get_profile_status",
                request_method="GET",
                request_path="/api/v1/profiles/status",
                call_status="failed",
                http_status=exc.status_code,
                error_code="agent_client_error",
                error_message=str(exc),
                latency_ms=self._elapsed_ms(started_at),
                retry_of_log_id=retry_of_log_id,
            )
            logger.error("profile_readiness_fetch_failed", user_id=user_id, error=str(exc))
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Unable to verify profile readiness") from exc

        readiness = self._extract_readiness_payload(payload)
        if not isinstance(readiness, dict):
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Invalid profile readiness response")

        # Seed student profile from orchestrator user data when no profile exists yet.
        if readiness.get("updated_at") is None:
            await self._seed_profile_if_missing(
                user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                retry_of_log_id=retry_of_log_id,
            )
            refresh_started_at = time.perf_counter()
            try:
                refreshed_payload = await self.student_profile_client.get_profile_status(
                    user_id=user_id,
                    intent=normalized_intent,
                )
                await self._record_agent_call(
                    user_id=user_id,
                    chat_id=chat_id,
                    workflow_run_id=workflow_run_id,
                    operation="get_profile_status",
                    request_method="GET",
                    request_path="/api/v1/profiles/status",
                    call_status="success",
                    response_payload=refreshed_payload if isinstance(refreshed_payload, dict) else None,
                    latency_ms=self._elapsed_ms(refresh_started_at),
                    retry_of_log_id=retry_of_log_id,
                )
                refreshed = self._extract_readiness_payload(refreshed_payload)
                if isinstance(refreshed, dict):
                    readiness = refreshed
            except AgentClientError as exc:
                await self._record_agent_call(
                    user_id=user_id,
                    chat_id=chat_id,
                    workflow_run_id=workflow_run_id,
                    operation="get_profile_status",
                    request_method="GET",
                    request_path="/api/v1/profiles/status",
                    call_status="failed",
                    http_status=exc.status_code,
                    error_code="agent_client_error",
                    error_message=str(exc),
                    latency_ms=self._elapsed_ms(refresh_started_at),
                    retry_of_log_id=retry_of_log_id,
                )
                logger.warning("profile_readiness_refresh_failed", user_id=user_id, error=str(exc))

        result = {
            "user_id": readiness.get("user_id", user_id),
            "profile_id": readiness.get("profile_id"),
            "missing_fields": list(readiness.get("missing_fields") or []),
            "optional_missing_fields": list(readiness.get("optional_missing_fields") or []),
            "updated_at": readiness.get("updated_at"),
            "intent": normalized_intent,
        }
        all_missing = set([*result["missing_fields"], *result["optional_missing_fields"]])
        required_by_intent = self.intent_registry_service.get_effective_required_fields(normalized_intent)
        optional_by_intent = self.intent_registry_service.get_effective_optional_fields(normalized_intent)

        result["missing_required_fields"] = [field for field in required_by_intent if field in all_missing]
        result["missing_optional_fields"] = [field for field in optional_by_intent if field in all_missing]
        result["completed"] = len(result["missing_required_fields"]) == 0

        logger.info(
            "profile_readiness_evaluated",
            user_id=result["user_id"],
            completed=result["completed"],
            missing_required_fields=result["missing_required_fields"],
            missing_optional_fields=result["missing_optional_fields"],
            intent=normalized_intent,
        )
        if readiness.get("updated_at") is not None:
            self._set_cached_readiness(cache_key, result)
        return result

    async def get_profile_clarifications(
        self,
        user_id: str,
        profile_id: str,
        *,
        chat_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
        retry_of_log_id: Optional[str] = None,
    ) -> dict[str, Any] | None:
        """Fetch the latest clarification queue and ReAct trace for a profile."""
        started_at = time.perf_counter()
        try:
            payload = await self.student_profile_client.get_profile_clarifications(
                profile_id=profile_id,
                user_id=user_id,
            )
            await self._record_agent_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="get_profile_clarifications",
                request_method="GET",
                request_path=f"/api/v1/profiles/{profile_id}/clarifications",
                call_status="success",
                response_payload=payload if isinstance(payload, dict) else None,
                latency_ms=self._elapsed_ms(started_at),
                retry_of_log_id=retry_of_log_id,
            )
            if not isinstance(payload, dict):
                return None
            data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            return data if isinstance(data, dict) else None
        except AgentClientError as exc:
            await self._record_agent_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="get_profile_clarifications",
                request_method="GET",
                request_path=f"/api/v1/profiles/{profile_id}/clarifications",
                call_status="failed",
                http_status=exc.status_code,
                error_code="agent_client_error",
                error_message=str(exc),
                latency_ms=self._elapsed_ms(started_at),
                retry_of_log_id=retry_of_log_id,
            )
            logger.warning(
                "profile_clarifications_fetch_failed", user_id=user_id, profile_id=profile_id, error=str(exc)
            )
            return None

    async def submit_profile_clarification_answers(
        self,
        user_id: str,
        profile_id: str,
        answers: list[dict[str, Any]],
        *,
        chat_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
        retry_of_log_id: Optional[str] = None,
    ) -> dict[str, Any] | None:
        """Submit chat replies to the active ReAct clarification queue."""
        started_at = time.perf_counter()
        try:
            payload = await self.student_profile_client.submit_profile_clarifications(
                profile_id=profile_id,
                user_id=user_id,
                answers=answers,
            )
            await self._record_agent_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="submit_profile_clarifications",
                request_method="POST",
                request_path=f"/api/v1/profiles/{profile_id}/clarifications",
                call_status="success",
                request_payload={"answers": answers},
                response_payload=payload if isinstance(payload, dict) else None,
                latency_ms=self._elapsed_ms(started_at),
                retry_of_log_id=retry_of_log_id,
            )
            if not isinstance(payload, dict):
                return None
            data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            if isinstance(data, dict):
                self.invalidate_readiness_cache(user_id)
            return data if isinstance(data, dict) else None
        except AgentClientError as exc:
            await self._record_agent_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="submit_profile_clarifications",
                request_method="POST",
                request_path=f"/api/v1/profiles/{profile_id}/clarifications",
                call_status="failed",
                http_status=exc.status_code,
                error_code="agent_client_error",
                error_message=str(exc),
                request_payload={"answers": answers},
                latency_ms=self._elapsed_ms(started_at),
                retry_of_log_id=retry_of_log_id,
            )
            logger.warning(
                "profile_clarification_submit_failed",
                user_id=user_id,
                profile_id=profile_id,
                error=str(exc),
            )
            return None

    @staticmethod
    def _extract_readiness_payload(payload: Any) -> Any:
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else payload

    async def _seed_profile_if_missing(
        self,
        user_id: str,
        *,
        chat_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
        retry_of_log_id: Optional[str] = None,
    ) -> None:
        """Create a baseline student profile from orchestrator user fields when absent."""
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            return

        first_name = (user.get("first_name") or "").strip()
        last_name = (user.get("last_name") or "").strip()
        full_name = " ".join(part for part in [first_name, last_name] if part).strip()
        email = (user.get("email") or "").strip()

        payload: dict[str, str] = {}
        if full_name:
            payload["full_name"] = full_name
        if email:
            payload["email"] = email

        if not payload:
            return

        started_at = time.perf_counter()
        try:
            await self.student_profile_client.sync_user_profile(user_id=user_id, payload=payload)
            await self._record_agent_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="sync_user_profile",
                request_method="POST",
                request_path="/api/v1/profiles/sync-user",
                call_status="success",
                request_payload={"user_id": user_id, **payload},
                latency_ms=self._elapsed_ms(started_at),
                retry_of_log_id=retry_of_log_id,
            )
            logger.info("student_profile_seeded_from_user", user_id=user_id, fields=list(payload.keys()))
        except AgentClientError as exc:
            await self._record_agent_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="sync_user_profile",
                request_method="POST",
                request_path="/api/v1/profiles/sync-user",
                call_status="failed",
                http_status=exc.status_code,
                error_code="agent_client_error",
                error_message=str(exc),
                request_payload={"user_id": user_id, **payload},
                latency_ms=self._elapsed_ms(started_at),
                retry_of_log_id=retry_of_log_id,
            )
            logger.warning("student_profile_seed_failed", user_id=user_id, error=str(exc))

    async def evaluate_gate(
        self,
        user_id: str,
        *,
        intent: Optional[str] = None,
        chat_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
        retry_of_log_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return allow/deny metadata for orchestration decisions."""
        readiness = await self.get_user_readiness(
            user_id,
            intent=intent,
            chat_id=chat_id,
            workflow_run_id=workflow_run_id,
            retry_of_log_id=retry_of_log_id,
        )
        allowed = bool(readiness["completed"])
        reason = "profile_complete_for_intent" if allowed else "profile_incomplete_for_intent"
        return {
            **readiness,
            "allowed": allowed,
            "reason": reason,
        }

    @classmethod
    def extract_profile_fields_from_chat(cls, content: str, missing_fields: list[str]) -> dict[str, Any]:
        """Public wrapper for chat extraction used by tests and orchestration."""
        return cls._extract_profile_fields_from_chat(content, missing_fields)

    @classmethod
    def extract_profile_field_candidates_from_chat(
        cls, content: str, missing_fields: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Public wrapper for chat extraction candidates used by tests and orchestration."""
        return cls._extract_profile_field_candidates_from_chat(content, missing_fields)

    async def collect_profile_updates_from_chat(
        self,
        user_id: str,
        content: str,
        missing_fields: list[str],
        *,
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
        retry_of_log_id: Optional[str] = None,
    ) -> dict[str, Any] | None:
        """Extract profile values from a chat turn and persist them when possible."""
        candidates = self._extract_profile_field_candidates_from_chat(content, missing_fields)
        if not candidates:
            return None

        extracted = {
            field: candidate.get("value")
            for field, candidate in candidates.items()
            if self._is_persistable_candidate(candidate)
        }
        pending_clarification_fields = [
            field
            for field, candidate in candidates.items()
            if field not in extracted and candidate.get("value") is not None
        ]
        correction_fields = [
            field
            for field, candidate in candidates.items()
            if bool(candidate.get("is_correction")) and field in extracted
        ]
        extraction_telemetry = self._build_extraction_telemetry(
            candidates=candidates,
            persisted_fields=list(extracted.keys()),
            pending_clarification_fields=pending_clarification_fields,
            correction_fields=correction_fields,
        )

        if not extracted:
            return {
                "applied_fields": [],
                "pending_clarification_fields": pending_clarification_fields,
                "correction_fields": [],
                "extraction_candidates": candidates,
                "extraction_telemetry": extraction_telemetry,
            }

        started_at = time.perf_counter()
        try:
            payload = await self.student_profile_client.collect_from_chat(
                user_id=user_id,
                fields=extracted,
                chat_id=chat_id,
                message_id=message_id,
                extraction_candidates=candidates,
                pending_clarification_fields=pending_clarification_fields,
                correction_fields=correction_fields,
                telemetry_summary=extraction_telemetry,
            )
            await self._record_agent_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="collect_from_chat",
                request_method="POST",
                request_path="/api/v1/profiles/collect-from-chat",
                call_status="success",
                request_payload={
                    "user_id": user_id,
                    "fields": extracted,
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "pending_clarification_fields": pending_clarification_fields,
                    "correction_fields": correction_fields,
                    "extraction_telemetry": extraction_telemetry,
                },
                response_payload=payload if isinstance(payload, dict) else None,
                latency_ms=self._elapsed_ms(started_at),
                retry_of_log_id=retry_of_log_id,
            )
            logger.info(
                "profile_fields_collected_from_chat",
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                extracted_fields=list(extracted.keys()),
                extraction_telemetry=extraction_telemetry,
            )
            if not isinstance(payload, dict):
                return None
            data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            if not isinstance(data, dict):
                return None
            data.setdefault("pending_clarification_fields", pending_clarification_fields)
            data.setdefault("correction_fields", correction_fields)
            data.setdefault("extraction_candidates", candidates)
            data.setdefault("extraction_telemetry", extraction_telemetry)
            self.invalidate_readiness_cache(user_id)
            return data
        except AgentClientError as exc:
            await self._record_agent_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="collect_from_chat",
                request_method="POST",
                request_path="/api/v1/profiles/collect-from-chat",
                call_status="failed",
                http_status=exc.status_code,
                error_code="agent_client_error",
                error_message=str(exc),
                request_payload={
                    "user_id": user_id,
                    "fields": extracted,
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "pending_clarification_fields": pending_clarification_fields,
                    "correction_fields": correction_fields,
                    "extraction_telemetry": extraction_telemetry,
                },
                latency_ms=self._elapsed_ms(started_at),
                retry_of_log_id=retry_of_log_id,
            )
            logger.warning(
                "profile_collect_from_chat_failed",
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                error=str(exc),
            )
            return None

    async def persist_profile_updates_from_chat(
        self,
        user_id: str,
        fields: dict[str, Any],
        *,
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
        retry_of_log_id: Optional[str] = None,
    ) -> dict[str, Any] | None:
        """Persist already-normalized profile updates derived from an active slot prompt."""
        explicit_fields = {key: value for key, value in (fields or {}).items() if value is not None}
        if not explicit_fields:
            return None

        started_at = time.perf_counter()
        try:
            payload = await self.student_profile_client.collect_from_chat(
                user_id=user_id,
                fields=explicit_fields,
                chat_id=chat_id,
                message_id=message_id,
            )
            await self._record_agent_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="collect_from_chat",
                request_method="POST",
                request_path="/api/v1/profiles/collect-from-chat",
                call_status="success",
                request_payload={
                    "user_id": user_id,
                    "fields": explicit_fields,
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "binding_mode": "active_profile_slot",
                },
                response_payload=payload if isinstance(payload, dict) else None,
                latency_ms=self._elapsed_ms(started_at),
                retry_of_log_id=retry_of_log_id,
            )
            if not isinstance(payload, dict):
                return None
            data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            if not isinstance(data, dict):
                return None
            self.invalidate_readiness_cache(user_id)
            return data
        except AgentClientError as exc:
            await self._record_agent_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="collect_from_chat",
                request_method="POST",
                request_path="/api/v1/profiles/collect-from-chat",
                call_status="failed",
                http_status=exc.status_code,
                error_code="agent_client_error",
                error_message=str(exc),
                request_payload={
                    "user_id": user_id,
                    "fields": explicit_fields,
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "binding_mode": "active_profile_slot",
                },
                latency_ms=self._elapsed_ms(started_at),
                retry_of_log_id=retry_of_log_id,
            )
            logger.warning(
                "profile_slot_persist_from_chat_failed",
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                error=str(exc),
            )
            return None

    def invalidate_readiness_cache(self, user_id: str, intent: Optional[str] = None) -> None:
        """Invalidate cached readiness snapshots for a user."""
        keys_to_delete = [
            key for key in self._READINESS_CACHE if key[0] == user_id and (intent is None or key[1] == intent)
        ]
        for key in keys_to_delete:
            self._READINESS_CACHE.pop(key, None)

    @classmethod
    def _readiness_cache_key(cls, user_id: str, intent: Optional[str]) -> tuple[str, str]:
        return user_id, intent or "profile_completion"

    @classmethod
    def _get_cached_readiness(cls, cache_key: tuple[str, str]) -> Optional[dict[str, Any]]:
        cached = cls._READINESS_CACHE.get(cache_key)
        if cached is None:
            return None

        expires_at, payload = cached
        if time.monotonic() >= expires_at:
            cls._READINESS_CACHE.pop(cache_key, None)
            return None

        cls._READINESS_CACHE.move_to_end(cache_key)
        return dict(payload)

    @classmethod
    def _set_cached_readiness(cls, cache_key: tuple[str, str], readiness: dict[str, Any]) -> None:
        cls._READINESS_CACHE[cache_key] = (
            time.monotonic() + cls._READINESS_CACHE_TTL_SECONDS,
            dict(readiness),
        )
        cls._READINESS_CACHE.move_to_end(cache_key)
        cls._prune_readiness_cache()

    @classmethod
    def _prune_readiness_cache(cls) -> None:
        now = time.monotonic()

        expired_keys = [key for key, (expires_at, _) in cls._READINESS_CACHE.items() if expires_at <= now]
        for key in expired_keys:
            cls._READINESS_CACHE.pop(key, None)

        while len(cls._READINESS_CACHE) > cls._READINESS_CACHE_MAX_ENTRIES:
            cls._READINESS_CACHE.popitem(last=False)

    async def _record_agent_call(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        *,
        user_id: str,
        chat_id: Optional[str],
        workflow_run_id: Optional[str],
        operation: str,
        request_method: Optional[str],
        request_path: Optional[str],
        call_status: str,
        http_status: Optional[int] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        request_payload: Optional[dict[str, Any]] = None,
        response_payload: Optional[dict[str, Any]] = None,
        latency_ms: Optional[int] = None,
        retry_of_log_id: Optional[str] = None,
    ) -> None:
        repo = self.agent_call_log_repo
        if repo is None:
            return

        try:
            await repo.create_log(
                log_id=str(uuid.uuid4()),
                workflow_run_id=workflow_run_id,
                user_id=user_id,
                chat_id=chat_id,
                target_service="student-profile",
                operation=operation,
                request_method=request_method,
                request_path=request_path,
                attempt_number=1,
                status=call_status,
                http_status=http_status,
                error_code=error_code,
                error_message=error_message,
                request_payload=request_payload,
                response_payload=response_payload,
                latency_ms=latency_ms,
                retry_of_log_id=retry_of_log_id,
            )
        except (aiomysql.Error, RuntimeError, ValueError, TypeError, AttributeError) as exc:  # pragma: no cover
            logger.warning("agent_call_log_write_failed", operation=operation, error=str(exc))

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((time.perf_counter() - started_at) * 1000))

    @classmethod
    def _extract_profile_fields_from_chat(cls, content: str, missing_fields: list[str]) -> dict[str, Any]:
        """Backward-compatible value-only view of extraction candidates."""
        candidates = cls._extract_profile_field_candidates_from_chat(content, missing_fields)
        return {
            field: candidate.get("value")
            for field, candidate in candidates.items()
            if candidate.get("value") is not None
        }

    @classmethod
    def _extract_profile_field_candidates_from_chat(
        cls, content: str, missing_fields: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Rule-first extraction with confidence and correction metadata."""
        text = (content or "").strip()
        if not text:
            return {}

        extracted: dict[str, dict[str, Any]] = {}
        missing = set(missing_fields)

        def set_candidate(
            field: str,
            value: Any,
            confidence: float,
            reason: str,
            *,
            source_span: Optional[str] = None,
            is_correction: bool = False,
            replaces_value: Optional[Any] = None,
        ) -> None:
            extracted[field] = {
                "value": value,
                "confidence": round(max(0.0, min(1.0, float(confidence))), 3),
                "reason": reason,
                "source_span": source_span,
                "is_correction": is_correction,
                "replaces_value": replaces_value,
            }

        if "email" in missing:
            email_match = re.search(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", text, flags=re.IGNORECASE)
            if email_match:
                value = email_match.group(0)
                set_candidate("email", value, 0.99, "explicit_email", source_span=value)

        if "full_name" in missing:
            name_match = re.search(r"\bmy name is\s+([A-Za-z][A-Za-z'\- ]{1,80})", text, flags=re.IGNORECASE)
            if name_match:
                value = name_match.group(1).strip(" .,")
                set_candidate("full_name", value, 0.95, "explicit_name_phrase", source_span=name_match.group(0))
            else:
                intro_name_match = re.search(
                    r"\b(?:i am|i'm)\s+([A-Za-z][A-Za-z'\- ]{1,80})", text, flags=re.IGNORECASE
                )
                if intro_name_match:
                    candidate = intro_name_match.group(1).strip(" .,")
                    if "@" not in candidate and len(candidate.split()) >= 2:
                        set_candidate(
                            "full_name", candidate, 0.9, "intro_name_phrase", source_span=intro_name_match.group(0)
                        )

        if "gpa" in missing or "gpa_scale" in missing:
            ratio_match = re.search(r"\b([0-9](?:\.[0-9]{1,2})?)\s*/\s*([0-9]{1,3}(?:\.[0-9])?)\b", text)
            if ratio_match:
                set_candidate("gpa", float(ratio_match.group(1)), 0.95, "gpa_ratio", source_span=ratio_match.group(0))
                set_candidate(
                    "gpa_scale", float(ratio_match.group(2)), 0.95, "gpa_ratio", source_span=ratio_match.group(0)
                )
            else:
                out_of_match = re.search(
                    r"\bgpa\s*(?:is|:|=)?\s*([0-9](?:\.[0-9]{1,2})?)\s*(?:out of|over)\s*([0-9]{1,3}(?:\.[0-9])?)\b",
                    text,
                    flags=re.IGNORECASE,
                )
                if out_of_match:
                    set_candidate(
                        "gpa", float(out_of_match.group(1)), 0.93, "gpa_out_of", source_span=out_of_match.group(0)
                    )
                    set_candidate(
                        "gpa_scale", float(out_of_match.group(2)), 0.93, "gpa_out_of", source_span=out_of_match.group(0)
                    )

                gpa_match = re.search(r"\bgpa\s*(?:is|:|=)?\s*([0-9](?:\.[0-9]{1,2})?)\b", text, flags=re.IGNORECASE)
                if gpa_match:
                    gpa_value = float(gpa_match.group(1))
                    set_candidate("gpa", gpa_value, 0.9, "explicit_gpa", source_span=gpa_match.group(0))
                    if "gpa_scale" in missing and "gpa_scale" not in extracted:
                        inferred_scale = 4.0 if gpa_value <= 4.0 else (5.0 if gpa_value <= 5.0 else 100.0)
                        set_candidate("gpa_scale", inferred_scale, 0.72, "inferred_from_gpa_value")

            if "gpa_scale" in missing and "gpa_scale" not in extracted:
                gpa_scale_match = re.search(
                    r"\b(?:gpa scale|scale)\s*(?:is|:|=)?\s*([0-9]{1,3}(?:\.[0-9])?)\b", text, flags=re.IGNORECASE
                )
                if gpa_scale_match:
                    set_candidate(
                        "gpa_scale",
                        float(gpa_scale_match.group(1)),
                        0.9,
                        "explicit_scale",
                        source_span=gpa_scale_match.group(0),
                    )

        degree_map = {
            "high school": "high_school",
            "highschool": "high_school",
            "bachelor": "bachelor",
            "master": "master",
            "phd": "phd",
            "doctorate": "phd",
        }
        lowered = text.lower()

        corrected_degree = cls._extract_corrected_degree_level(lowered, degree_map)
        if corrected_degree:
            set_candidate(
                "target_degree_level",
                corrected_degree,
                0.92,
                "degree_level_correction",
                source_span=text,
                is_correction=True,
            )

        if "current_degree_level" in missing:
            for needle, normalized in degree_map.items():
                if re.search(
                    rf"\b(current|currently|i am|i'm|studying|doing|student|degree).{{0,30}}\b{re.escape(needle)}\b",
                    lowered,
                ):
                    set_candidate("current_degree_level", normalized, 0.9, "current_degree_context", source_span=needle)
                    break

        bare_degree = cls._extract_bare_degree_level_candidate(lowered, degree_map)
        if (
            bare_degree
            and "current_degree_level" in missing
            and "target_degree_level" in missing
            and "current_degree_level" not in extracted
            and "target_degree_level" not in extracted
        ):
            set_candidate("current_degree_level", bare_degree, 0.88, "bare_degree_answer", source_span=text)

        if "target_degree_level" in missing and "target_degree_level" not in extracted:
            for needle, normalized in degree_map.items():
                if re.search(
                    rf"\b(target|goal|plan|planning|want|aim|pursu(?:e|ing)|apply(?:ing)?|intend|"
                    rf"looking for).{{0,30}}\b{re.escape(needle)}\b",
                    lowered,
                ):
                    set_candidate("target_degree_level", normalized, 0.9, "target_degree_context", source_span=needle)
                    break

            if "target_degree_level" not in extracted:
                if bare_degree and "current_degree_level" not in extracted:
                    set_candidate("target_degree_level", bare_degree, 0.88, "bare_degree_answer", source_span=text)

        corrected_study_field = cls._extract_inline_correction_value(text)
        if corrected_study_field and cls._looks_like_bare_study_field(corrected_study_field):
            set_candidate(
                "intended_field_of_study",
                corrected_study_field.title(),
                0.9,
                "study_field_correction",
                source_span=text,
                is_correction=True,
            )

        if "intended_field_of_study" in missing and "intended_field_of_study" not in extracted:
            study_fields = cls._extract_study_field_candidates(text)
            if study_fields:
                candidate_value: Any = study_fields[0] if len(study_fields) == 1 else study_fields
                confidence = 0.88 if len(study_fields) == 1 else 0.7
                reason = (
                    "single_study_field_candidate" if len(study_fields) == 1 else "ambiguous_study_field_candidates"
                )
                set_candidate("intended_field_of_study", candidate_value, confidence, reason, source_span=text)

        corrected_country = cls._extract_corrected_country_candidate(text)
        if corrected_country:
            set_candidate(
                "target_study_country",
                corrected_country,
                0.92,
                "country_correction",
                source_span=text,
                is_correction=True,
            )

        if "target_study_country" in missing and "target_study_country" not in extracted:
            countries = cls._extract_country_candidates(text)
            if countries:
                country_value: Any = countries[0] if len(countries) == 1 else countries
                confidence = 0.9 if len(countries) == 1 else 0.68
                reason = "single_country_candidate" if len(countries) == 1 else "ambiguous_country_candidates"
                set_candidate("target_study_country", country_value, confidence, reason, source_span=text)
            else:
                # Try to infer country from university mentions (e.g., "MIT" → "United States")
                inferred_country = cls._infer_country_from_university(text)
                if inferred_country:
                    set_candidate(
                        "target_study_country",
                        inferred_country,
                        0.88,
                        "inferred_from_university_mention",
                        source_span=text,
                    )

        if "enrollment_timeline" in missing:
            timelines = cls._extract_timeline_candidates(text)
            if timelines:
                timeline_value: Any = timelines[0] if len(timelines) == 1 else timelines
                confidence = 0.9 if len(timelines) == 1 else 0.7
                reason = "single_timeline_candidate" if len(timelines) == 1 else "ambiguous_timeline_candidates"
                set_candidate("enrollment_timeline", timeline_value, confidence, reason, source_span=text)

        if "funding_source" in missing:
            funding = cls._extract_funding_candidates(text)
            if funding:
                funding_value: Any = funding[0] if len(funding) == 1 else funding
                confidence = 0.86 if len(funding) == 1 else 0.72
                reason = "single_funding_candidate" if len(funding) == 1 else "ambiguous_funding_candidates"
                set_candidate("funding_source", funding_value, confidence, reason, source_span=text)

        return extracted

    @classmethod
    def _is_persistable_candidate(cls, candidate: dict[str, Any]) -> bool:
        value = candidate.get("value")
        if value is None:
            return False
        confidence = candidate.get("confidence")
        try:
            score = float(confidence)
        except (TypeError, ValueError):
            return False
        return score >= cls._AUTO_PERSIST_CONFIDENCE_THRESHOLD

    @staticmethod
    def _extract_inline_correction_value(text: str) -> Optional[str]:
        patterns = [
            r"\b(?:actually|instead|rather|change(?:\s+it)?\s+to)\s+([A-Za-z][A-Za-z&/'\- ]{2,80})",
            r"\bnot\s+[A-Za-z][A-Za-z&/'\- ]{2,80}\s*(?:,|but)\s*([A-Za-z][A-Za-z&/'\- ]{2,80})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                candidate = match.group(1).strip(" .,")
                candidate = re.sub(r"\b(?:instead|rather|actually)\b$", "", candidate, flags=re.IGNORECASE)
                return candidate.strip(" .,") or None
        return None

    @classmethod
    def _extract_corrected_country_candidate(cls, text: str) -> Optional[str]:
        corrected = cls._extract_inline_correction_value(text)
        if not corrected:
            return None
        return cls._normalize_country_candidate(corrected)

    @staticmethod
    def _extract_corrected_degree_level(text: str, degree_map: dict[str, str]) -> Optional[str]:
        correction_pattern = re.search(
            r"\b(?:actually|instead|rather|change(?:\s+it)?\s+to|not\s+[a-z ]+\s*(?:,|but))\s*"
            r"(?:to\s+)?(high school|highschool|bachelor|master|phd|doctorate)\b",
            text,
            flags=re.IGNORECASE,
        )
        if not correction_pattern:
            return None

        corrected = correction_pattern.group(1).lower()
        return degree_map.get(corrected)

    @staticmethod
    def _build_extraction_telemetry(
        *,
        candidates: dict[str, dict[str, Any]],
        persisted_fields: list[str],
        pending_clarification_fields: list[str],
        correction_fields: list[str],
    ) -> dict[str, Any]:
        candidate_fields = [field for field, candidate in candidates.items() if candidate.get("value") is not None]
        candidate_count = len(candidate_fields)
        persisted_count = len(set(persisted_fields))
        clarification_count = len(set(pending_clarification_fields))
        correction_count = len(set(correction_fields))

        denominator = candidate_count if candidate_count > 0 else 1
        return {
            "candidate_count": candidate_count,
            "persisted_count": persisted_count,
            "correction_count": correction_count,
            "clarification_count": clarification_count,
            "hit_rate": round(persisted_count / denominator, 4),
            "correction_rate": round(correction_count / denominator, 4),
            "clarification_rate": round(clarification_count / denominator, 4),
        }

    @staticmethod
    def _unique_ordered(items: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for item in items:
            normalized = item.strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(normalized)
        return unique

    @staticmethod
    def _clean_candidate_text(value: str) -> str:
        cleaned = value.strip(" .,")
        cleaned = re.sub(r"^(?:is|in|to|for|at)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(?:study|studying|applying)\s+(?:in|to)\s+", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip(" .,")

    @classmethod
    def _extract_study_field_candidates(cls, text: str) -> list[str]:
        patterns = [
            r"(?:field of study|major|speciali[sz]ation)\s*(?:is|:)?\s*([A-Za-z][A-Za-z&/\- ]{2,100})",
            r"(?:interested in|want to study|planning to study|study)\s+([A-Za-z][A-Za-z&/\- ]{2,100})",
        ]
        values: list[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                phrase = match.group(1).strip(" .,")
                parts = re.split(r"\s*(?:,|/|\bor\b|\band\b)\s*", phrase, flags=re.IGNORECASE)
                for part in parts:
                    cleaned = cls._clean_candidate_text(part)
                    if len(cleaned) >= 3:
                        values.append(cleaned.title())

        if not values:
            bare = cls._clean_candidate_text(text)
            if cls._looks_like_bare_study_field(bare):
                values.append(bare.title())
        return cls._unique_ordered(values)

    @staticmethod
    def _looks_like_bare_study_field(value: str) -> bool:
        normalized = value.strip()
        if not normalized:
            return False

        if len(normalized) > 80:
            return False

        if not re.fullmatch(r"[A-Za-z][A-Za-z&/'\- ]{1,79}", normalized):
            return False

        lowered = normalized.lower()
        if lowered.startswith(_BLOCKED_FIELD_PREFIXES):
            return False

        if lowered in _NON_ACADEMIC_DESCRIPTORS:
            return False

        if lowered in _DEGREE_KEYWORDS:
            return False

        if lowered in _DEGREE_PHRASES:
            return False

        return len(normalized.split()) <= 5

    @staticmethod
    def _extract_bare_degree_level_candidate(text: str, degree_map: dict[str, str]) -> Optional[str]:
        normalized_text = text.strip().strip(".,").lower()
        if not normalized_text:
            return None

        for needle, normalized in degree_map.items():
            if normalized_text == needle:
                return normalized

        if normalized_text in _DEGREE_PHRASE_MAP:
            return _DEGREE_PHRASE_MAP[normalized_text]

        return None

    @classmethod
    def _extract_country_candidates(cls, text: str) -> list[str]:
        lowered = text.lower()
        found: list[str] = []
        # Accept uppercase "US" as United States but avoid matching lowercase pronoun "us".
        if re.search(r"\bUS\b", text):
            found.append("United States")

        for alias, canonical in cls._COUNTRY_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", lowered):
                found.append(canonical)

        country_phrase_patterns = [
            r"(?:study|studying|apply|applying|target|prefer|want|plan(?:ning)?|looking)\s+"
            r"(?:in|to)\s+([A-Za-z][A-Za-z\s\-']{2,80})",
            r"(?:country|destination)\s*(?:is|:)?\s*([A-Za-z][A-Za-z\s\-']{2,80})",
            # Match "[Country] is my preferred country" or "preferred country is [Country]"
            r"([A-Za-z][A-Za-z\s\-']{2,40})\s+is\s+(?:my\s+)?(?:preferred|target|chosen|desired)\s+"
            r"(?:country|destination|place)",
            # Match "my preferred country is [Country]" (already covered above) or "prefer [Country]"
            r"\bprefer(?:red)?\s+(?:to\s+study\s+in\s+)?([A-Za-z][A-Za-z\s\-']{2,40})\b",
        ]
        trailing_noise = re.compile(
            r"\b(next year|this year|soon|eventually|maybe|for now|for admission|for intake)\b.*$",
            flags=re.IGNORECASE,
        )

        for pattern in country_phrase_patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                phrase = trailing_noise.sub("", match.group(1)).strip(" .,")
                parts = re.split(r"\s*(?:,|/|\bor\b|\band\b)\s*", phrase, flags=re.IGNORECASE)
                for part in parts:
                    cleaned = cls._clean_candidate_text(part)
                    if len(cleaned) < 3:
                        continue
                    normalized = cls._normalize_country_candidate(cleaned)
                    if normalized:
                        found.append(normalized)

        # If text is short (likely a direct answer to "what's your preferred country?"),
        # try to normalize the entire text as a country name
        if not found and len(text.split()) <= 3:
            potential_country = cls._normalize_country_candidate(text)
            if potential_country:
                found.append(potential_country)

        return cls._unique_ordered(found)

    @classmethod
    def _normalize_country_candidate(cls, value: str) -> Optional[str]:
        normalized = cls._clean_candidate_text(value).lower()
        if not normalized:
            return None

        if normalized in cls._COUNTRY_ALIASES:
            return cls._COUNTRY_ALIASES[normalized]

        try:
            country = pycountry.countries.lookup(normalized)
        except LookupError:
            return None

        if getattr(country, "name", None):
            return str(country.name)

        return None

    @classmethod
    def _extract_timeline_candidates(cls, text: str) -> list[str]:
        season_year_pattern = r"\b(spring|summer|fall|autumn|winter)\s+(20\d{2})\b"
        year_season_pattern = r"\b(20\d{2})\s*(?:-|/)??\s*(spring|summer|fall|autumn|winter)\b"
        month_tokens = "|".join(sorted(cls._MONTH_ALIASES.keys(), key=len, reverse=True))
        month_year_pattern = rf"\b({month_tokens})\s+(20\d{{2}})\b"
        year_month_pattern = rf"\b(20\d{{2}})\s*(?:-|/)??\s*({month_tokens})\b"

        values: list[str] = []
        for season, year in re.findall(season_year_pattern, text, flags=re.IGNORECASE):
            label = f"{season.title()} {year}"
            if label.lower().startswith("autumn"):
                label = f"Fall {year}"
            values.append(label)

        for year, season in re.findall(year_season_pattern, text, flags=re.IGNORECASE):
            normalized_season = "Fall" if season.lower() == "autumn" else season.title()
            values.append(f"{normalized_season} {year}")

        for month, year in re.findall(month_year_pattern, text, flags=re.IGNORECASE):
            normalized_month = cls._MONTH_ALIASES.get(month.lower())
            if normalized_month:
                values.append(f"{normalized_month} {year}")

        for year, month in re.findall(year_month_pattern, text, flags=re.IGNORECASE):
            normalized_month = cls._MONTH_ALIASES.get(month.lower())
            if normalized_month:
                values.append(f"{normalized_month} {year}")

        return cls._unique_ordered(values)

    @classmethod
    def _infer_country_from_university(cls, text: str) -> Optional[str]:
        """Infer study country from university mentions (e.g., 'MIT' → 'United States')."""
        lowered = text.lower()

        # University patterns mapped to countries
        university_country_map = {
            # US Universities
            "mit": "United States",
            "massachusetts institute of technology": "United States",
            "stanford": "United States",
            "harvard": "United States",
            "yale": "United States",
            "princeton": "United States",
            "columbia": "United States",
            "berkeley": "United States",
            "uc berkeley": "United States",
            "ucla": "United States",
            "caltech": "United States",
            "carnegie mellon": "United States",
            "cmu": "United States",
            "nyu": "United States",
            "upenn": "United States",
            "penn": "United States",
            "cornell": "United States",
            "duke": "United States",
            "northwestern": "United States",
            "uchicago": "United States",
            "johns hopkins": "United States",
            "georgia tech": "United States",
            # UK Universities
            "oxford": "United Kingdom",
            "cambridge": "United Kingdom",
            "imperial": "United Kingdom",
            "imperial college": "United Kingdom",
            "ucl": "United Kingdom",
            "lse": "United Kingdom",
            "edinburgh": "United Kingdom",
            "manchester": "United Kingdom",
            "kings college": "United Kingdom",
            "kcl": "United Kingdom",
            # Singapore Universities
            "nus": "Singapore",
            "national university of singapore": "Singapore",
            "ntu": "Singapore",
            "nanyang": "Singapore",
            "nanyang technological": "Singapore",
            "smu": "Singapore",
            "singapore management": "Singapore",
            "sutd": "Singapore",
            # Switzerland
            "eth zurich": "Switzerland",
            "eth": "Switzerland",
            "epfl": "Switzerland",
            # Canada
            "toronto": "Canada",
            "mcgill": "Canada",
            # Australia
            "melbourne": "Australia",
            "sydney": "Australia",
            "anu": "Australia",
            # China
            "tsinghua": "China",
            "peking": "China",
            # Japan
            "tokyo": "Japan",
            "kyoto": "Japan",
            # South Korea
            "seoul national": "South Korea",
            "kaist": "South Korea",
        }

        for pattern, country in university_country_map.items():
            if re.search(rf"\b{re.escape(pattern)}\b", lowered):
                return country
        return None

    @classmethod
    def _extract_funding_candidates(cls, text: str) -> list[str]:
        lowered = text.lower()
        funding_patterns = [
            (r"\b(scholarship|scholarships|grant|grants|fellowship|fellowships|fully funded)\b", "scholarship"),
            (
                r"\b(self[- ]?fund(?:ed|ing)?|personal savings|own funds|out[- ]of[- ]pocket|pay myself|my savings)\b",
                "self_funded",
            ),
            (r"\b(loan|student loan|education loan|bank loan)\b", "loan"),
            (r"\b(sponsor|sponsorship|sponsored|employer[- ]sponsored|company sponsorship)\b", "sponsorship"),
            (r"\b(parent|parents|family support|family funded|parents support)\b", "family_support"),
            (r"\b(assistantship|teaching assistantship|research assistantship|ta ship|ra ship)\b", "assistantship"),
        ]

        matches: list[tuple[int, str]] = []
        for pattern, normalized in funding_patterns:
            for match in re.finditer(pattern, lowered, flags=re.IGNORECASE):
                matches.append((match.start(), normalized))

        matches.sort(key=lambda item: item[0])
        found = [normalized for _, normalized in matches]
        return cls._unique_ordered(found)
