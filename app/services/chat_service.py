"""Chat session business logic — create, send messages, list, delete."""

# pylint: disable=too-many-lines

import base64
import binascii
import hashlib
import json
import re
import time
import uuid
from collections import OrderedDict
from datetime import datetime
from typing import Any, Optional

import aiomysql
from fastapi import HTTPException, status

from app.clients.agent_client import AgentClientError
from app.clients.application_support_client import ApplicationSupportClient
from app.clients.program_discovery_client import ProgramDiscoveryClient
from app.clients.scholarship_discovery_client import ScholarshipDiscoveryClient
from app.core.database import get_pool
from app.core.logging import get_logger
from app.models.applications import TrackedApplicationCreate
from app.models.results import DiscoverRequest
from app.repositories.agent_call_log_repo import AgentCallLogRepository
from app.repositories.chat_repo import ChatRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.project_repo import ProjectRepository
from app.repositories.user_repo import UserRepository
from app.repositories.workflow_run_repo import WorkflowRunRepository
from app.services.agent_availability_service import AgentAvailabilityService
from app.services.application_support_keywords import APPLICATION_SUPPORT_KEYWORDS, detect_application_support_action
from app.services.application_tracking_service import ApplicationTrackingService
from app.services.eligibility_service import EligibilityEvaluationInput, EligibilityService
from app.services.intent_registry_service import IntentRegistryService
from app.services.profile_gate_service import ProfileGateService
from app.services.result_aggregation_service import ResultAggregationService

logger = get_logger(__name__)

MAX_AUTO_TITLE_LENGTH = 50


def _lazy_chat_repo() -> ChatRepository:
    return ChatRepository(get_pool())


def _lazy_message_repo() -> MessageRepository:
    return MessageRepository(get_pool())


def _lazy_project_repo() -> ProjectRepository:
    return ProjectRepository(get_pool())


def _lazy_profile_gate_service() -> ProfileGateService:
    return ProfileGateService()


def _lazy_workflow_run_repo() -> WorkflowRunRepository:
    return WorkflowRunRepository(get_pool())


def _lazy_agent_call_log_repo() -> AgentCallLogRepository:
    return AgentCallLogRepository(get_pool())


def _lazy_intent_registry_service() -> IntentRegistryService:
    return IntentRegistryService()


def _lazy_agent_availability_service() -> AgentAvailabilityService:
    return AgentAvailabilityService()


def _lazy_program_discovery_client() -> ProgramDiscoveryClient:
    return ProgramDiscoveryClient()


def _lazy_scholarship_discovery_client() -> ScholarshipDiscoveryClient:
    return ScholarshipDiscoveryClient()


def _lazy_application_support_client() -> ApplicationSupportClient:
    return ApplicationSupportClient()


def _lazy_application_tracking_service() -> ApplicationTrackingService:
    return ApplicationTrackingService()


def _lazy_result_aggregation_service() -> ResultAggregationService:
    return ResultAggregationService()


def _lazy_eligibility_service() -> EligibilityService:
    return EligibilityService()


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if value is None:
        return []
    return [str(value)]


class ChatService:  # pylint: disable=too-many-public-methods,too-many-instance-attributes
    """Orchestrates chat session operations."""

    _RESPONSE_CACHE_TTL_SECONDS = 90
    _RESPONSE_CACHE_MAX_ENTRIES = 256
    _RESPONSE_CACHE: OrderedDict[tuple[str, str], tuple[float, dict[str, Any]]] = OrderedDict()

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        chat_repo: Optional[ChatRepository] = None,
        message_repo: Optional[MessageRepository] = None,
        project_repo: Optional[ProjectRepository] = None,
        profile_gate_service: Optional[ProfileGateService] = None,
        workflow_run_repo: Optional[WorkflowRunRepository] = None,
        agent_call_log_repo: Optional[AgentCallLogRepository] = None,
        intent_registry_service: Optional[IntentRegistryService] = None,
        agent_availability_service: Optional[AgentAvailabilityService] = None,
        program_discovery_client: Optional[ProgramDiscoveryClient] = None,
        scholarship_discovery_client: Optional[ScholarshipDiscoveryClient] = None,
        application_support_client: Optional[ApplicationSupportClient] = None,
        application_tracking_service: Optional[ApplicationTrackingService] = None,
        result_aggregation_service: Optional[ResultAggregationService] = None,
        eligibility_service: Optional[EligibilityService] = None,
    ) -> None:
        self._eligibility_service = eligibility_service
        self._chat_repo = chat_repo
        self._message_repo = message_repo
        self._project_repo = project_repo
        self._profile_gate_service = profile_gate_service
        self._workflow_run_repo = workflow_run_repo
        self._agent_call_log_repo = agent_call_log_repo
        self._intent_registry_service = intent_registry_service
        self._agent_availability_service = agent_availability_service
        self._program_discovery_client = program_discovery_client
        self._scholarship_discovery_client = scholarship_discovery_client
        self._application_support_client = application_support_client
        self._application_tracking_service = application_tracking_service
        self._result_aggregation_service = result_aggregation_service

    @classmethod
    def _build_response_cache_key(
        cls,
        chat_id: str,
        content: str,
        detected_intent: str,
        gate: dict[str, Any],
        target_agent: Optional[str],
    ) -> tuple[str, str]:
        normalized_content = re.sub(r"\s+", " ", (content or "").strip()).lower()
        content_digest = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
        readiness_signature = {
            "allowed": bool(gate.get("allowed")),
            "reason": str(gate.get("reason") or ""),
            "missing_required_fields": sorted(str(field) for field in gate.get("missing_required_fields") or []),
            "missing_optional_fields": sorted(str(field) for field in gate.get("missing_optional_fields") or []),
            "updated_at": str(gate.get("updated_at") or ""),
            "target_agent": target_agent or "",
        }
        signature_text = json.dumps(readiness_signature, sort_keys=True, separators=(",", ":"))
        return chat_id, f"{detected_intent}:{content_digest}:{signature_text}"

    @classmethod
    def _get_cached_response(cls, cache_key: tuple[str, str]) -> Optional[dict[str, Any]]:
        cached = cls._RESPONSE_CACHE.get(cache_key)
        if cached is None:
            return None

        expires_at, payload = cached
        if time.monotonic() >= expires_at:
            cls._RESPONSE_CACHE.pop(cache_key, None)
            return None

        cls._RESPONSE_CACHE.move_to_end(cache_key)
        return dict(payload)

    @classmethod
    def _set_cached_response(cls, cache_key: tuple[str, str], payload: dict[str, Any]) -> None:
        cls._RESPONSE_CACHE[cache_key] = (time.monotonic() + cls._RESPONSE_CACHE_TTL_SECONDS, dict(payload))
        cls._RESPONSE_CACHE.move_to_end(cache_key)
        cls._evict_expired_and_overflow_entries()

    @classmethod
    def _evict_expired_and_overflow_entries(cls) -> None:
        now = time.monotonic()

        expired_keys = [key for key, (expires_at, _) in cls._RESPONSE_CACHE.items() if expires_at <= now]
        for key in expired_keys:
            cls._RESPONSE_CACHE.pop(key, None)

        while len(cls._RESPONSE_CACHE) > cls._RESPONSE_CACHE_MAX_ENTRIES:
            cls._RESPONSE_CACHE.popitem(last=False)

    @property
    def chat_repo(self) -> ChatRepository:
        if self._chat_repo is None:
            self._chat_repo = _lazy_chat_repo()
        return self._chat_repo

    @property
    def message_repo(self) -> MessageRepository:
        if self._message_repo is None:
            self._message_repo = _lazy_message_repo()
        return self._message_repo

    @property
    def project_repo(self) -> ProjectRepository:
        if self._project_repo is None:
            self._project_repo = _lazy_project_repo()
        return self._project_repo

    @property
    def profile_gate_service(self) -> ProfileGateService:
        if self._profile_gate_service is None:
            self._profile_gate_service = _lazy_profile_gate_service()
        return self._profile_gate_service

    @property
    def workflow_run_repo(self) -> Optional[WorkflowRunRepository]:
        if self._workflow_run_repo is None:
            try:
                self._workflow_run_repo = _lazy_workflow_run_repo()
            except RuntimeError:
                return None
        return self._workflow_run_repo

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

    @property
    def agent_availability_service(self) -> AgentAvailabilityService:
        if self._agent_availability_service is None:
            self._agent_availability_service = _lazy_agent_availability_service()
        return self._agent_availability_service

    @property
    def program_discovery_client(self) -> ProgramDiscoveryClient:
        if self._program_discovery_client is None:
            self._program_discovery_client = _lazy_program_discovery_client()
        return self._program_discovery_client

    @property
    def scholarship_discovery_client(self) -> ScholarshipDiscoveryClient:
        if self._scholarship_discovery_client is None:
            self._scholarship_discovery_client = _lazy_scholarship_discovery_client()
        return self._scholarship_discovery_client

    @property
    def application_support_client(self) -> ApplicationSupportClient:
        if self._application_support_client is None:
            self._application_support_client = _lazy_application_support_client()
        return self._application_support_client

    @property
    def application_tracking_service(self) -> ApplicationTrackingService:
        if self._application_tracking_service is None:
            self._application_tracking_service = _lazy_application_tracking_service()
        return self._application_tracking_service

    @property
    def result_aggregation_service(self) -> ResultAggregationService:
        if self._result_aggregation_service is None:
            self._result_aggregation_service = _lazy_result_aggregation_service()
        return self._result_aggregation_service

    @property
    def eligibility_service(self) -> EligibilityService:
        if self._eligibility_service is None:
            self._eligibility_service = _lazy_eligibility_service()
        return self._eligibility_service

    # -- Public API --

    async def create_chat(
        self,
        user_id: str,
        initial_message: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Create a new chat session.

        If project_id is provided, validates ownership and increments chat_count.
        If initial_message is provided, sends it and auto-generates title.
        """
        if project_id:
            exists = await self.project_repo.exists_for_user(project_id, user_id)
            if not exists:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

        chat_id = str(uuid.uuid4())

        chat = await self.chat_repo.create(
            chat_id=chat_id,
            user_id=user_id,
            title=None,
            project_id=project_id,
        )

        if project_id:
            await self.project_repo.increment_chat_count(project_id, 1)

        if initial_message:
            result = await self.send_message(
                user_id=user_id,
                chat_id=chat_id,
                content=initial_message,
            )
            return result["chat"]

        logger.info("chat_created", user_id=user_id, chat_id=chat_id, project_id=project_id, with_message=False)
        return chat

    async def get_chat(self, user_id: str, chat_id: str) -> dict[str, Any]:
        """Get a single chat by ID. Validates ownership."""
        chat = await self._get_chat_or_404(chat_id, user_id)
        return chat

    async def list_chats(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        self,
        user_id: str,
        limit: int = 20,
        cursor: Optional[str] = None,
        starred: Optional[bool] = None,
        project_id: Optional[str] = None,
        no_project: bool = False,
    ) -> dict[str, Any]:
        """
        List user's chats with cursor pagination and filters.

        Filters:
        - starred: True = only starred, False = only non-starred, None = all
        - project_id: Filter by specific project
        - no_project: True = only chats without a project
        """
        limit = min(max(1, limit), 100)

        cursor_dt: Optional[datetime] = None
        if cursor:
            try:
                decoded = base64.b64decode(cursor).decode("utf-8")
                cursor_dt = datetime.fromisoformat(decoded)
            except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor") from exc

        if project_id:
            exists = await self.project_repo.exists_for_user(project_id, user_id)
            if not exists:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

        chats, total_count = await self.chat_repo.list_by_user(
            user_id=user_id,
            limit=limit,
            cursor=cursor_dt,
            starred=starred,
            project_id=project_id,
            no_project=no_project,
        )

        next_cursor: Optional[str] = None
        if chats and len(chats) == limit:
            last_updated = chats[-1].get("updated_at")
            if last_updated:
                cursor_str = last_updated.isoformat() if isinstance(last_updated, datetime) else str(last_updated)
                next_cursor = base64.b64encode(cursor_str.encode("utf-8")).decode("utf-8")

        return {
            "chats": chats,
            "next_cursor": next_cursor,
            "total_count": total_count,
        }

    async def update_chat(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        user_id: str,
        chat_id: str,
        title: Optional[str] = None,
        is_starred: Optional[bool] = None,
        project_id: Optional[str] = None,
        remove_from_project: bool = False,
    ) -> dict[str, Any]:
        """
        Update chat metadata (title, starred status, project assignment).

        To remove from project, pass remove_from_project=True or project_id as empty string.
        """
        chat = await self._get_chat_or_404(chat_id, user_id)
        old_project_id = chat.get("project_id")

        if title is not None:
            await self.chat_repo.update_title(chat_id, title)

        if is_starred is not None:
            await self.chat_repo.update_starred(chat_id, is_starred)

        if remove_from_project or project_id == "":
            if old_project_id:
                await self.chat_repo.update_project(chat_id, None)
                await self.project_repo.increment_chat_count(old_project_id, -1)
        elif project_id is not None:
            exists = await self.project_repo.exists_for_user(project_id, user_id)
            if not exists:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

            await self.chat_repo.update_project(chat_id, project_id)

            if old_project_id and old_project_id != project_id:
                await self.project_repo.increment_chat_count(old_project_id, -1)
            if project_id != old_project_id:
                await self.project_repo.increment_chat_count(project_id, 1)

        updated_chat = await self.chat_repo.get_by_id(chat_id)
        logger.info("chat_updated", user_id=user_id, chat_id=chat_id)
        return updated_chat  # type: ignore

    async def delete_chat(self, user_id: str, chat_id: str) -> None:
        """Soft delete a chat. Validates ownership. Updates project chat_count."""
        chat = await self._get_chat_or_404(chat_id, user_id)
        project_id = chat.get("project_id")

        deleted = await self.chat_repo.soft_delete(chat_id)
        if not deleted:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")

        if project_id:
            await self.project_repo.increment_chat_count(project_id, -1)

        logger.info("chat_deleted", user_id=user_id, chat_id=chat_id)

    async def send_message(  # pylint: disable=too-many-locals
        self,
        user_id: str,
        chat_id: str,
        content: str,
        retry_of_log_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Send a user message and receive assistant response."""
        chat = await self._get_chat_or_404(chat_id, user_id)
        workflow_run_id = str(uuid.uuid4())
        await self._create_workflow_run(
            workflow_run_id=workflow_run_id,
            user_id=user_id,
            chat_id=chat_id,
            workflow_type="profile_gate_chat_turn",
            workflow_state="RECEIVED",
            context={"retry_of_log_id": retry_of_log_id} if retry_of_log_id else None,
        )

        latest_assistant_message = await self._get_latest_assistant_message(chat_id)
        user_message_id = str(uuid.uuid4())
        try:
            user_message = await self.message_repo.create(
                message_id=user_message_id,
                chat_id=chat_id,
                role="user",
                content=content,
                metadata=None,
            )
            logger.info("message_sent", user_id=user_id, chat_id=chat_id, message_id=user_message_id, role="user")

            detected_intent = self.intent_registry_service.detect_intent(content)
            detected_intent = self._maybe_override_intent_for_clarification_reply(
                detected_intent,
                content,
                latest_assistant_message,
            )
            is_eligibility_clarification_reply = (
                isinstance(latest_assistant_message, dict)
                and isinstance(latest_assistant_message.get("metadata"), dict)
                and latest_assistant_message["metadata"].get("pending_intent") == "eligibility_check"
            )
            pending_eligibility_context = (
                latest_assistant_message.get("metadata", {}).get("pending_eligibility_context")
                if isinstance(latest_assistant_message, dict)
                and isinstance(latest_assistant_message.get("metadata"), dict)
                else None
            )
            pending_application_support_context = (
                latest_assistant_message.get("metadata", {}).get("pending_application_support_context")
                if isinstance(latest_assistant_message, dict)
                and isinstance(latest_assistant_message.get("metadata"), dict)
                else None
            )
            intent_policy = self.intent_registry_service.get_policy(detected_intent)
            target_agent = intent_policy.get("agent") if isinstance(intent_policy, dict) else None
            cached_response: dict[str, Any] | None = None
            active_profile_slot: dict[str, Any] | None = None
            collected_from_chat: dict[str, Any] | None = None
            agent_reasoning_from_response: dict[str, Any] | None = None
            pending_intent_for_next_turn: str | None = None
            pending_eligibility_context_for_next_turn: dict[str, Any] | None = None
            pending_application_support_context_for_next_turn: dict[str, Any] | None = None
            response_dict: dict[str, Any] = {}

            if detected_intent == "out_of_scope":
                assistant_content = self._build_out_of_scope_response(intent_policy)
                gate = {
                    "allowed": False,
                    "reason": "intent_out_of_scope",
                    "intent": detected_intent,
                    "missing_fields": [],
                    "missing_required_fields": [],
                    "missing_optional_fields": [],
                }
            elif (
                target_agent
                and target_agent != "student-profile"
                and not await self.agent_availability_service.is_agent_available(target_agent)
            ):
                if target_agent == "program-discovery":
                    await self._attempt_program_discovery_probe(user_id=user_id, chat_id=chat_id)
                assistant_content = self._build_agent_unavailable_response(detected_intent, target_agent)
                gate = {
                    "allowed": False,
                    "reason": "intent_agent_unavailable",
                    "intent": detected_intent,
                    "target_agent": target_agent,
                    "missing_fields": [],
                    "missing_required_fields": [],
                    "missing_optional_fields": [],
                }
            else:
                gate = await self.profile_gate_service.evaluate_gate(
                    user_id,
                    intent=detected_intent,
                    chat_id=chat_id,
                    workflow_run_id=workflow_run_id,
                    retry_of_log_id=retry_of_log_id,
                )
                cache_key = self._build_response_cache_key(chat_id, content, detected_intent, gate, target_agent)
                cached_response = self._get_cached_response(cache_key)

                if cached_response is not None:
                    assistant_content = cached_response["assistant_content"]
                    gate = cached_response["gate"]
                    target_agent = cached_response.get("target_agent", target_agent)
                    agent_reasoning_from_response = cached_response.get("agent_reasoning_from_response")
                    pending_intent_for_next_turn = cached_response.get("pending_intent_for_next_turn")
                    pending_eligibility_context_for_next_turn = cached_response.get(
                        "pending_eligibility_context_for_next_turn"
                    )
                    pending_application_support_context_for_next_turn = cached_response.get(
                        "pending_application_support_context_for_next_turn"
                    )
                else:
                    agent_reasoning_from_response = None
                    pending_intent_for_next_turn = None
                    pending_eligibility_context_for_next_turn = None
                    pending_application_support_context_for_next_turn = None
                    clarification_question: Optional[str] = None
                    clarification_field: Optional[str] = None
                    active_profile_slot = None

                    if not gate["allowed"]:
                        gate, collected_from_chat, clarification_field, clarification_question = (
                            await self._handle_blocked_profile_gate_turn(
                                user_id=user_id,
                                chat_id=chat_id,
                                content=content,
                                user_message_id=user_message_id,
                                detected_intent=detected_intent,
                                latest_assistant_message=latest_assistant_message,
                                gate=gate,
                                workflow_run_id=workflow_run_id,
                                retry_of_log_id=retry_of_log_id,
                            )
                        )

                    response_dict, gate = await self._resolve_assistant_content(
                        gate=gate,
                        collected_from_chat=collected_from_chat,
                        clarification_question=clarification_question,
                        detected_intent=detected_intent,
                        target_agent=target_agent,
                        user_id=user_id,
                        chat_id=chat_id,
                        content=content,
                        workflow_run_id=workflow_run_id,
                        is_eligibility_clarification_reply=is_eligibility_clarification_reply,
                        pending_eligibility_context=pending_eligibility_context,
                        pending_application_support_context=pending_application_support_context,
                    )
                    assistant_content = response_dict.get("answer", "")
                    agent_reasoning_from_response = response_dict.get("agent_reasoning")
                    pending_intent_for_next_turn = response_dict.get("pending_intent") or None
                    pending_eligibility_context_for_next_turn = response_dict.get("pending_eligibility_context")
                    pending_application_support_context_for_next_turn = response_dict.get(
                        "pending_application_support_context"
                    )

                    # Keep domain-intent continuity across profile-gate clarification turns.
                    # Example: "what about scholarship for me" -> blocked for missing profile
                    # field -> user answers "Singapore". The follow-up should continue
                    # scholarship_search rather than being recast as profile_completion.
                    if (
                        not pending_intent_for_next_turn
                        and gate.get("allowed") is False
                        and str(gate.get("reason") or "") == "profile_incomplete_for_intent"
                        and detected_intent not in {"profile_completion", "out_of_scope"}
                    ):
                        pending_intent_for_next_turn = detected_intent
                    if (
                        pending_intent_for_next_turn in {"application_planning", "apply_to_named_school"}
                        and not pending_application_support_context_for_next_turn
                    ):
                        pending_application_support_context_for_next_turn = (
                            self._build_pending_application_support_context(
                                content,
                                detected_intent,
                            )
                        )

                    active_profile_slot = self._build_active_profile_slot(
                        clarification_field=clarification_field,
                        missing_fields=_as_string_list(
                            gate.get("missing_required_fields") or gate.get("missing_fields") or []
                        ),
                        clarification_question=clarification_question,
                        assistant_content=assistant_content,
                    )

                    self._set_cached_response(
                        cache_key,
                        {
                            "assistant_content": assistant_content,
                            "agent_reasoning_from_response": agent_reasoning_from_response,
                            "gate": gate,
                            "target_agent": target_agent,
                            "active_profile_slot": active_profile_slot,
                            "pending_intent_for_next_turn": pending_intent_for_next_turn,
                            "pending_eligibility_context_for_next_turn": pending_eligibility_context_for_next_turn,
                            "pending_application_support_context_for_next_turn": (
                                pending_application_support_context_for_next_turn
                            ),
                        },
                    )

            logger.info(
                "profile_gate_decision",
                user_id=user_id,
                chat_id=chat_id,
                allowed=gate["allowed"],
                reason=gate["reason"],
                missing_fields=gate.get("missing_fields") or [],
                missing_required_fields=gate.get("missing_required_fields") or [],
                missing_optional_fields=gate.get("missing_optional_fields") or [],
                intent=detected_intent,
            )

            assistant_message_id = str(uuid.uuid4())
            selected_agent = self._resolve_selected_agent(
                gate=gate,
                target_agent=target_agent,
                detected_intent=detected_intent,
            )
            assistant_metadata: dict[str, Any] = {
                "profile_gate": gate,
                "workflow_run_id": workflow_run_id,
                "retry_of_log_id": retry_of_log_id,
                "intent": detected_intent,
                "active_profile_slot": (
                    (cached_response or {}).get("active_profile_slot")
                    if cached_response is not None
                    else active_profile_slot
                ),
                "orchestrator_thoughts": self._build_orchestrator_thoughts(
                    detected_intent=detected_intent,
                ),
                "gate_decision": self._build_gate_decision(gate),
                "routing_decision": self._build_routing_decision(
                    selected_agent=selected_agent,
                    target_agent=target_agent,
                    gate=gate,
                    detected_intent=detected_intent,
                ),
            }
            agent_reasoning = self._build_agent_reasoning(  # pylint: disable=unexpected-keyword-arg
                gate=gate,
                collected_from_chat=collected_from_chat,
                agent_reasoning_from_response=agent_reasoning_from_response,
            )
            if agent_reasoning is not None:
                assistant_metadata["agent_reasoning"] = agent_reasoning
            _pending = (
                (cached_response or {}).get("pending_intent_for_next_turn")
                if cached_response is not None
                else pending_intent_for_next_turn
            )
            if _pending:
                assistant_metadata["pending_intent"] = _pending
            _pending_eligibility_context = (
                (cached_response or {}).get("pending_eligibility_context_for_next_turn")
                if cached_response is not None
                else pending_eligibility_context_for_next_turn
            )
            if isinstance(_pending_eligibility_context, dict) and _pending_eligibility_context:
                assistant_metadata["pending_eligibility_context"] = _pending_eligibility_context
            _pending_application_support_context = (
                (cached_response or {}).get("pending_application_support_context_for_next_turn")
                if cached_response is not None
                else pending_application_support_context_for_next_turn
            )
            if isinstance(_pending_application_support_context, dict) and _pending_application_support_context:
                assistant_metadata["pending_application_support_context"] = _pending_application_support_context
            refresh_tabs = response_dict.get("refresh_tabs") if isinstance(response_dict, dict) else None
            if isinstance(refresh_tabs, list) and refresh_tabs:
                assistant_metadata["refresh_tabs"] = [str(tab) for tab in refresh_tabs if tab]
            focus_application_id = (
                response_dict.get("focus_application_id") if isinstance(response_dict, dict) else None
            )
            if isinstance(focus_application_id, str) and focus_application_id.strip():
                assistant_metadata["focus_application_id"] = focus_application_id.strip()

            assistant_message = await self.message_repo.create(
                message_id=assistant_message_id,
                chat_id=chat_id,
                role="assistant",
                content=assistant_content,
                metadata=assistant_metadata,
            )
            logger.info(
                "message_sent", user_id=user_id, chat_id=chat_id, message_id=assistant_message_id, role="assistant"
            )

            await self.chat_repo.increment_message_count(chat_id, increment=2)

            if chat.get("message_count", 0) == 0:
                auto_title = self._generate_title_from_message(content)
                await self.chat_repo.set_title_if_empty(chat_id, auto_title)

            updated_chat = await self.chat_repo.get_by_id(chat_id)
            await self._complete_workflow_run(
                workflow_run_id=workflow_run_id,
                workflow_status="success",
                workflow_state=(
                    "SUCCESS"
                    if gate["allowed"]
                    else (
                        "ROUTE_TARGET_AGENT"
                        if gate.get("reason") in {"intent_out_of_scope", "intent_agent_unavailable"}
                        else "PROFILE_GATE"
                    )
                ),
                context={
                    "intent": detected_intent,
                    "target_agent": target_agent,
                    "missing_fields": _as_string_list(gate.get("missing_fields") or []),
                    "missing_required_fields": _as_string_list(gate.get("missing_required_fields") or []),
                    "missing_optional_fields": _as_string_list(gate.get("missing_optional_fields") or []),
                },
            )

            return {
                "user_message": user_message,
                "assistant_message": assistant_message,
                "chat": updated_chat,
            }
        except (HTTPException, AgentClientError, aiomysql.Error, RuntimeError, ValueError, TypeError) as exc:
            await self._complete_workflow_run(
                workflow_run_id=workflow_run_id,
                workflow_status="failed",
                workflow_state="FAILED_TERMINAL",
                error_message=str(exc),
            )
            raise

    async def _handle_blocked_profile_gate_turn(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        self,
        *,
        user_id: str,
        chat_id: str,
        content: str,
        user_message_id: str,
        detected_intent: str,
        latest_assistant_message: Optional[dict[str, Any]],
        gate: dict[str, Any],
        workflow_run_id: str,
        retry_of_log_id: Optional[str],
    ) -> tuple[dict[str, Any], Optional[dict[str, Any]], Optional[str], Optional[str]]:
        clarification_submission: dict[str, Any] | None = None
        clarification_field: Optional[str] = None
        clarification_question: Optional[str] = None
        collected_from_chat: dict[str, Any] | None = None
        routed_to_react_clarification = False
        profile_id = gate.get("profile_id")
        latest_active_slot = self._extract_active_profile_slot(latest_assistant_message)

        if profile_id and latest_active_slot is not None and latest_active_slot.get("source") == "clarification_queue":
            first_clarification_field = str(latest_active_slot.get("field") or "").strip()
            if first_clarification_field:
                clarification_submission = await self.profile_gate_service.submit_profile_clarification_answers(
                    user_id=user_id,
                    profile_id=str(profile_id),
                    answers=[
                        {
                            "field": first_clarification_field,
                            "value": content.strip(),
                        }
                    ],
                    chat_id=chat_id,
                    workflow_run_id=workflow_run_id,
                    retry_of_log_id=retry_of_log_id,
                )
                routed_to_react_clarification = clarification_submission is not None

        if (
            not routed_to_react_clarification
            and profile_id
            and self._is_profile_gate_followup_prompt(latest_assistant_message)
        ):
            clarifications_before = await self.profile_gate_service.get_profile_clarifications(
                user_id=user_id,
                profile_id=str(profile_id),
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                retry_of_log_id=retry_of_log_id,
            )
            first_clarification_field = self._extract_clarification_field(clarifications_before)
            # Bind replies to the active clarification-queue field even when it is
            # outside intent-required gate fields (for example optional profile
            # fields like publications asked by the profile agent).
            if first_clarification_field:
                clarification_submission = await self.profile_gate_service.submit_profile_clarification_answers(
                    user_id=user_id,
                    profile_id=str(profile_id),
                    answers=[
                        {
                            "field": first_clarification_field,
                            "value": content.strip(),
                        }
                    ],
                    chat_id=chat_id,
                    workflow_run_id=workflow_run_id,
                    retry_of_log_id=retry_of_log_id,
                )
                routed_to_react_clarification = clarification_submission is not None

        if not routed_to_react_clarification and latest_active_slot is not None:
            slot_updates = self._extract_slot_bound_profile_updates(content, latest_active_slot)
            if slot_updates:
                collected_from_chat = await self.profile_gate_service.persist_profile_updates_from_chat(
                    user_id=user_id,
                    fields=slot_updates,
                    chat_id=chat_id,
                    message_id=user_message_id,
                    workflow_run_id=workflow_run_id,
                    retry_of_log_id=retry_of_log_id,
                )
                routed_to_react_clarification = collected_from_chat is not None

        if not routed_to_react_clarification:
            # Include both required AND optional missing fields for extraction
            # This allows users to provide optional fields like target_study_country voluntarily
            missing_required = _as_string_list(gate.get("missing_required_fields") or [])
            missing_optional = _as_string_list(gate.get("missing_optional_fields") or [])
            missing_fields = list(set(missing_required + missing_optional))
            collected_from_chat = await self.profile_gate_service.collect_profile_updates_from_chat(
                user_id=user_id,
                content=content,
                missing_fields=missing_fields,
                chat_id=chat_id,
                message_id=user_message_id,
                workflow_run_id=workflow_run_id,
                retry_of_log_id=retry_of_log_id,
            )
            if not isinstance(collected_from_chat, dict):
                collected_from_chat = None

        refreshed_gate = await self.profile_gate_service.evaluate_gate(
            user_id,
            intent=detected_intent,
            chat_id=chat_id,
            workflow_run_id=workflow_run_id,
            retry_of_log_id=retry_of_log_id,
        )
        if refreshed_gate.get("profile_id"):
            clarifications = clarification_submission
            if not isinstance(clarifications, dict):
                clarifications = await self.profile_gate_service.get_profile_clarifications(
                    user_id=user_id,
                    profile_id=str(refreshed_gate["profile_id"]),
                    chat_id=chat_id,
                    workflow_run_id=workflow_run_id,
                    retry_of_log_id=retry_of_log_id,
                )
            clarification_field = self._extract_clarification_field(clarifications)
            clarification_question = self._extract_clarification_question(clarifications)

        # When routed via clarification submission, propagate applied_fields so the
        # response formatter can emit "Great, I saved your X." on the next question.
        if isinstance(clarification_submission, dict) and collected_from_chat is None:
            submission_applied = _as_string_list(clarification_submission.get("applied_fields"))
            if submission_applied:
                collected_from_chat = {"applied_fields": submission_applied}

        return refreshed_gate, collected_from_chat, clarification_field, clarification_question

    async def post_assistant_notice(
        self,
        *,
        user_id: str,
        chat_id: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Persist an assistant-authored notice message for system-driven follow-ups."""
        chat = await self._get_chat_or_404(chat_id, user_id)
        message_metadata = self._augment_metadata_with_active_profile_slot(metadata, content)

        assistant_message_id = str(uuid.uuid4())
        assistant_message = await self.message_repo.create(
            message_id=assistant_message_id,
            chat_id=chat_id,
            role="assistant",
            content=content,
            metadata=message_metadata,
        )

        await self.chat_repo.increment_message_count(chat_id, increment=1)

        # When upload flow starts a chat without a user message, derive a title
        # from the first assistant notice so the chat is not shown as untitled.
        if int(chat.get("message_count") or 0) == 0:
            preferred_title = None
            if isinstance(message_metadata, dict):
                candidate_title = message_metadata.get("notice_title")
                if isinstance(candidate_title, str) and candidate_title.strip():
                    preferred_title = candidate_title.strip()

            auto_title = preferred_title or self._generate_title_from_message(content)
            await self.chat_repo.set_title_if_empty(chat_id, auto_title)

        updated_chat = await self.chat_repo.get_by_id(chat_id)

        logger.info(
            "assistant_notice_posted",
            user_id=user_id,
            chat_id=chat_id,
            message_id=assistant_message_id,
        )

        return {
            "assistant_message": assistant_message,
            "chat": updated_chat,
        }

    async def get_messages(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        self,
        user_id: str,
        chat_id: str,
        limit: int = 50,
        cursor: Optional[str] = None,
        order: str = "asc",
    ) -> dict[str, Any]:
        """
        Get message history for a chat with cursor pagination.

        Cursor format: base64-encoded JSON {"t": "ISO-timestamp", "id": "message-uuid"}
        Uses (created_at, id) for stable ordering across identical timestamps.
        """
        await self._get_chat_or_404(chat_id, user_id)

        limit = min(max(1, limit), 100)

        if order.lower() not in ("asc", "desc"):
            order = "asc"

        cursor_time: Optional[datetime] = None
        cursor_id: Optional[str] = None
        if cursor:
            try:
                decoded = base64.b64decode(cursor).decode("utf-8")
                cursor_data = json.loads(decoded)
                cursor_time = datetime.fromisoformat(cursor_data["t"])
                cursor_id = cursor_data["id"]
            except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor") from exc

        messages = await self.message_repo.list_by_chat(
            chat_id=chat_id,
            limit=limit,
            cursor_time=cursor_time,
            cursor_id=cursor_id,
            order=order,
        )

        next_cursor: Optional[str] = None
        if messages and len(messages) == limit:
            last_msg = messages[-1]
            last_created = last_msg.get("created_at")
            last_id = last_msg.get("id")
            if last_created and last_id:
                cursor_str = last_created.isoformat() if isinstance(last_created, datetime) else str(last_created)
                cursor_data = json.dumps({"t": cursor_str, "id": last_id})
                next_cursor = base64.b64encode(cursor_data.encode("utf-8")).decode("utf-8")

        return {
            "messages": messages,
            "next_cursor": next_cursor,
        }

    async def retry_last_agent_call(self, user_id: str, chat_id: str) -> dict[str, Any]:
        """Retry orchestration by replaying the latest user message in this chat."""
        await self._get_chat_or_404(chat_id, user_id)
        retry_of_log_id: Optional[str] = None
        failed_log = await self._get_latest_failed_agent_call_log(user_id=user_id, chat_id=chat_id)
        if failed_log:
            retry_of_log_id = str(failed_log.get("id") or "") or None

        recent_messages = await self.message_repo.list_by_chat(chat_id=chat_id, limit=50, order="desc")
        latest_user_message = next((msg for msg in recent_messages if msg.get("role") == "user"), None)
        if not latest_user_message:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No user message available to retry")

        send_result = await self.send_message(
            user_id=user_id,
            chat_id=chat_id,
            content=str(latest_user_message.get("content") or ""),
            retry_of_log_id=retry_of_log_id,
        )
        assistant_message = send_result.get("assistant_message") or {}

        return {
            "chat_id": chat_id,
            "retried": True,
            "source_message_id": latest_user_message.get("id"),
            "retry_of_log_id": retry_of_log_id,
            "assistant_message": assistant_message,
            "profile_gate": (assistant_message.get("metadata") or {}).get("profile_gate"),
            "chat": send_result.get("chat"),
        }

    async def _attempt_program_discovery_probe(self, *, user_id: str, chat_id: str) -> None:
        """Best-effort probe call to program-discovery; failures are expected during rollout."""
        try:
            await self.program_discovery_client.probe_health(
                user_id=user_id,
                session_id=chat_id,
            )
            logger.info("program_discovery_probe_succeeded", user_id=user_id, chat_id=chat_id)
        except AgentClientError as exc:
            logger.warning(
                "program_discovery_probe_failed",
                user_id=user_id,
                chat_id=chat_id,
                status_code=exc.status_code,
                error=str(exc),
            )

    async def _handle_program_discovery(
        self,
        *,
        user_id: str,
        chat_id: str,
        content: str,
        workflow_run_id: str,
        gate: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Call Program Discovery Agent to answer a program-related question.

        Uses PDA's /chat/ask endpoint which has LLM integration (OpenAI/Anthropic)
        and access to institutions with QS World Rankings data.
        Falls back to a helpful message if the PDA call fails.

        Returns:
            Dict with 'answer' (str) and optional 'agent_reasoning' (dict).
        """
        started_at = time.perf_counter()

        student_profile = await self._get_student_profile_for_agents(user_id, gate or {})

        try:
            result = await self.program_discovery_client.ask_question(
                question=content,
                student_profile=student_profile,
                include_explainability=True,
                user_id=user_id,
                session_id=chat_id,
            )

            await self._record_program_discovery_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="chat_ask",
                request_method="POST",
                request_path="/chat/ask",
                call_status="success",
                request_payload={"question": content, "student_profile": student_profile},
                response_payload=self._truncate_response_for_logging(result),
                latency_ms=self._elapsed_ms(started_at),
            )

            if isinstance(result, dict):
                answer = result.get("answer") or result.get("response")
                if not answer and isinstance(result.get("data"), dict):
                    answer = result["data"].get("answer") or result["data"].get("response")
                if answer and isinstance(answer, str) and answer.strip():
                    return {
                        "answer": answer.strip(),
                        "agent_reasoning": result.get("agent_reasoning"),
                        "source": "program_discovery",
                        "dashboard_items": self._build_program_dashboard_items_from_chat_result(result),
                    }

            logger.warning(
                "program_discovery_unexpected_response_shape",
                user_id=user_id,
                chat_id=chat_id,
                response_keys=list(result.keys()) if isinstance(result, dict) else type(result).__name__,
            )
            return {
                "answer": (
                    "I found some information about programs but had trouble formatting the response. "
                    "Could you try rephrasing your question? For example, ask about specific fields, "
                    "countries, or universities."
                ),
                "agent_reasoning": None,
                "source": "program_discovery",
                "dashboard_items": [],
            }

        except AgentClientError as exc:
            await self._record_program_discovery_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="chat_ask",
                request_method="POST",
                request_path="/chat/ask",
                call_status="failed",
                http_status=exc.status_code,
                error_code="agent_client_error",
                error_message=str(exc),
                request_payload={"question": content},
                latency_ms=self._elapsed_ms(started_at),
            )
            logger.error(
                "program_discovery_call_failed",
                user_id=user_id,
                chat_id=chat_id,
                status_code=exc.status_code,
                error=str(exc),
            )
            return {
                "answer": (
                    "I tried to look up program information for you, but the program discovery "
                    "service encountered an issue. Please try again in a moment."
                ),
                "agent_reasoning": None,
                "source": "program_discovery",
                "dashboard_items": [],
            }
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "program_discovery_unexpected_error",
                user_id=user_id,
                chat_id=chat_id,
                error=str(exc),
            )
            return {
                "answer": ("I ran into an unexpected issue while searching for programs. " "Please try again shortly."),
                "agent_reasoning": None,
                "source": "program_discovery",
                "dashboard_items": [],
            }

    async def _persist_chat_dashboard_snapshot(
        self,
        *,
        user_id: str,
        chat_id: str,
        detected_intent: str,
        content: str,
        programs: Optional[list[dict[str, Any]]] = None,
        scholarships: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        try:
            await self.result_aggregation_service.persist_chat_dashboard_snapshot(
                user_id=user_id,
                chat_id=chat_id,
                source_intent=detected_intent,
                source_message=content,
                programs=programs,
                scholarships=scholarships,
                agents={
                    "chat-sync": {
                        "status": "success",
                        "intent": detected_intent,
                    }
                },
            )
            logger.info(
                "dashboard_chat_snapshot_persisted",
                user_id=user_id,
                chat_id=chat_id,
                intent=detected_intent,
                program_count=len(programs or []),
                scholarship_count=len(scholarships or []),
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "dashboard_chat_snapshot_persist_failed",
                error=str(exc),
                user_id=user_id,
                chat_id=chat_id,
                intent=detected_intent,
            )

    @classmethod
    def _build_program_dashboard_items_from_chat_result(cls, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []

        direct_items = payload.get("programs")
        if isinstance(direct_items, list) and direct_items and isinstance(direct_items[0], dict):
            return [dict(item) for item in direct_items if isinstance(item, dict)]

        reasoning = payload.get("agent_reasoning")
        if not isinstance(reasoning, dict):
            return []

        entries = cls._select_program_entries_for_dashboard(
            reasoning.get("ranking_breakdown"),
            payload.get("programs_mentioned"),
        )

        items: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            program_name = cls._first_text(entry.get("program_name"), "Unnamed program")
            institution_name = cls._first_text(entry.get("university"), "Unknown institution")
            program_id = cls._first_text(entry.get("program_id"))
            if not program_id:
                program_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        (
                            "chat-program:"
                            f"{cls._normalize_match_text(program_name)}:"
                            f"{cls._normalize_match_text(institution_name)}"
                        ),
                    )
                )
            item = {
                "id": program_id,
                "program_name": program_name,
                "institution_name": institution_name,
                "institution_country": cls._first_text(entry.get("country"), ""),
                "ranking": {
                    "rank": entry.get("rank"),
                    "decision": entry.get("decision"),
                    "match_scores": entry.get("match_scores"),
                    "evidence": entry.get("evidence"),
                },
                "match": cls._build_chat_match_summary(
                    entry.get("composite_score"),
                    confidence_level=entry.get("decision"),
                ),
            }
            items.append(item)
        return items

    @classmethod
    def _select_program_entries_for_dashboard(
        cls,
        ranking_breakdown: Any,
        programs_mentioned: Any,
    ) -> list[dict[str, Any]]:
        entries = [entry for entry in (ranking_breakdown or []) if isinstance(entry, dict)]
        if not entries:
            return []

        mentions = [mention for mention in (programs_mentioned or []) if isinstance(mention, str) and mention.strip()]
        if not mentions:
            return entries

        matched_entries: list[dict[str, Any]] = []
        used_indexes: set[int] = set()

        for mention in mentions:
            for index, entry in enumerate(entries):
                if index in used_indexes:
                    continue
                if cls._program_entry_matches_mention(entry, mention):
                    matched_entries.append(entry)
                    used_indexes.add(index)
                    break

        return matched_entries or entries

    @classmethod
    def _program_entry_matches_mention(cls, entry: dict[str, Any], mention: str) -> bool:
        normalized_mention = cls._normalize_match_text(mention)
        if not normalized_mention:
            return False

        program_name = cls._first_text(entry.get("program_name"))
        institution_name = cls._first_text(entry.get("university"))
        normalized_program = cls._normalize_match_text(program_name)
        normalized_institution = cls._normalize_match_text(institution_name)

        if normalized_program and normalized_program == normalized_mention:
            return True

        combined_label = cls._normalize_match_text(f"{program_name} {institution_name}".strip())
        combined_with_at = cls._normalize_match_text(f"{program_name} at {institution_name}".strip())
        for candidate in (combined_label, combined_with_at):
            if candidate and (candidate == normalized_mention or candidate in normalized_mention):
                return True

        if normalized_program and normalized_program in normalized_mention:
            if not normalized_institution:
                return True
            institution_tokens = normalized_institution.split()
            return any(token and token in normalized_mention for token in institution_tokens)

        return False

    @classmethod
    def _build_scholarship_dashboard_items_from_chat_result(cls, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []

        items = payload.get("data")
        if not isinstance(items, list):
            return []

        reasoning = payload.get("agent_reasoning")
        breakdown_by_id: dict[str, dict[str, Any]] = {}
        if isinstance(reasoning, dict):
            for entry in reasoning.get("matching_breakdown") or []:
                if not isinstance(entry, dict):
                    continue
                scholarship_id = entry.get("scholarship_id")
                if scholarship_id is None:
                    continue
                breakdown_by_id[str(scholarship_id)] = entry

        normalized_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            breakdown = breakdown_by_id.get(str(item.get("id")))
            score_value = None
            confidence_level = None
            if isinstance(breakdown, dict):
                score_value = breakdown.get("composite_score")
                confidence_level = breakdown.get("decision")
                normalized["ranking"] = {
                    "rank": breakdown.get("rank"),
                    "decision": breakdown.get("decision"),
                    "match_scores": breakdown.get("match_scores"),
                    "match_evidence": breakdown.get("match_evidence"),
                    "eligibility_check": breakdown.get("eligibility_check"),
                }
            elif item.get("match_confidence") is not None:
                score_value = item.get("match_confidence")

            match_summary = cls._build_chat_match_summary(score_value, confidence_level=confidence_level)
            if match_summary is not None:
                normalized["match"] = match_summary
            normalized_items.append(normalized)
        return normalized_items

    @classmethod
    def _build_chat_match_summary(
        cls,
        score: Any,
        *,
        confidence_level: Any = None,
    ) -> Optional[dict[str, Any]]:
        normalized_score = cls._normalize_chat_match_score(score)
        if normalized_score is None and confidence_level is None:
            return None
        return {
            "match_score": normalized_score,
            "confidence_level": str(confidence_level) if confidence_level is not None else None,
        }

    @staticmethod
    def _normalize_chat_match_score(score: Any) -> Optional[float]:
        try:
            numeric = float(score)
        except (TypeError, ValueError):
            return None
        if 0 <= numeric <= 1:
            return round(numeric * 100, 2)
        return round(numeric, 2)

    @classmethod
    def _build_discover_request_from_chat(cls, content: str) -> DiscoverRequest:
        lowered = f" {content.lower()} "
        return DiscoverRequest(
            query=content,
            target_field=cls._extract_target_field(lowered),
            target_degree=cls._extract_target_degree(lowered),
            countries=cls._extract_country_preferences(lowered),
            limit=10,
            include_attribution=True,
            force_refresh=True,
        )

    @staticmethod
    def _extract_country_preferences(lowered: str) -> list[str]:
        country_patterns = [
            ("singapore", "Singapore"),
            ("united kingdom", "United Kingdom"),
            (" uk ", "United Kingdom"),
            ("u.k.", "United Kingdom"),
            ("england", "United Kingdom"),
            ("united states", "United States"),
            (" usa ", "United States"),
            ("u.s.", "United States"),
            ("canada", "Canada"),
            ("australia", "Australia"),
        ]
        return [country for token, country in country_patterns if token in lowered]

    @staticmethod
    def _extract_target_degree(lowered: str) -> Optional[str]:
        if any(token in lowered for token in ("phd", "ph.d", "doctorate", "doctoral")):
            return "phd"
        if any(token in lowered for token in ("master", "masters", "msc", "ms ", "graduate")):
            return "master"
        if any(token in lowered for token in ("bachelor", "undergraduate")):
            return "bachelor"
        return None

    @staticmethod
    def _extract_target_field(lowered: str) -> Optional[str]:
        if any(token in lowered for token in ("artificial intelligence", "machine learning", " ai ")):
            return "Artificial Intelligence"
        if "data science" in lowered:
            return "Data Science"
        if any(token in lowered for token in ("computer science", "computing", " cs ")):
            return "Computer Science"
        if "business" in lowered or "mba" in lowered:
            return "Business"
        if "engineering" in lowered:
            return "Engineering"
        return None

    def _format_aggregation_chat_response(self, *, dashboard: dict[str, Any], detected_intent: str) -> str:
        programs = self._dashboard_items(dashboard, "programs")
        scholarships = self._dashboard_items(dashboard, "scholarships")
        errors = dashboard.get("errors") if isinstance(dashboard.get("errors"), list) else []

        lines = ["I ran discovery and saved these results to your dashboard."]
        if detected_intent == "scholarship_search":
            lines.extend(self._format_scholarship_section(scholarships))
            lines.extend(self._format_program_section(programs))
        else:
            lines.extend(self._format_program_section(programs))
            lines.extend(self._format_scholarship_section(scholarships))

        if errors:
            first_error = errors[0] if isinstance(errors[0], dict) else {}
            message = first_error.get("message") if isinstance(first_error, dict) else None
            if message:
                lines.append(f"\nNote: one agent returned a partial result: {message}")

        lines.append("\nOpen the Programs or Scholarships tab to view the same saved results.")
        return "\n".join(lines)

    @staticmethod
    def _dashboard_items(dashboard: dict[str, Any], key: str) -> list[dict[str, Any]]:
        section = dashboard.get(key)
        if isinstance(section, dict) and isinstance(section.get("items"), list):
            return [item for item in section["items"] if isinstance(item, dict)]
        return []

    def _format_program_section(self, programs: list[dict[str, Any]]) -> list[str]:
        if not programs:
            return ["\nPrograms: no matched programs found in the latest discovery run."]

        lines = ["\nPrograms:"]
        for index, program in enumerate(programs[:5], start=1):
            name = self._first_text(program.get("program_name"), program.get("name"), "Unnamed program")
            institution = self._first_text(
                program.get("institution_name"),
                program.get("university"),
                program.get("provider"),
                "Unknown institution",
            )
            country = self._first_text(program.get("institution_country"), program.get("country"), "")
            score = self._format_score(program.get("match"))
            suffix = f" - {score}" if score else ""
            location = f", {country}" if country else ""
            lines.append(f"{index}. {name} - {institution}{location}{suffix}")
        return lines

    def _format_scholarship_section(self, scholarships: list[dict[str, Any]]) -> list[str]:
        if not scholarships:
            return ["\nScholarships: no matched scholarships found in the latest discovery run."]

        lines = ["\nScholarships:"]
        for index, scholarship in enumerate(scholarships[:5], start=1):
            name = self._first_text(scholarship.get("name"), scholarship.get("title"), "Unnamed scholarship")
            provider = self._first_text(scholarship.get("provider"), scholarship.get("organization"), "")
            amount = self._format_amount(scholarship)
            score = self._format_score(scholarship.get("match"))
            details = [value for value in (provider, amount, score) if value]
            suffix = f" - {'; '.join(details)}" if details else ""
            lines.append(f"{index}. {name}{suffix}")
        return lines

    @staticmethod
    def _first_text(*values: Any) -> str:
        fallback = ""
        if values:
            fallback = str(values[-1]) if values[-1] is not None else ""
        for value in values[:-1]:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return fallback

    @staticmethod
    def _format_score(match: Any) -> Optional[str]:
        if not isinstance(match, dict):
            return None
        try:
            score = float(match.get("match_score"))
        except (TypeError, ValueError):
            return None
        return f"{round(score)}% match"

    @staticmethod
    def _format_amount(scholarship: dict[str, Any]) -> Optional[str]:
        amount = scholarship.get("funding_amount")
        if isinstance(amount, (int, float)):
            currency = scholarship.get("currency") if isinstance(scholarship.get("currency"), str) else "USD"
            return f"{currency} {amount:,.0f}"
        raw_amount = scholarship.get("amount")
        if isinstance(raw_amount, str) and raw_amount.strip():
            return raw_amount.strip()
        return None

    async def _record_program_discovery_call(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        *,
        user_id: str,
        chat_id: Optional[str],
        workflow_run_id: Optional[str],
        operation: str,
        request_method: Optional[str],
        request_path: Optional[str],
        call_status: str,
        target_service: str = "program-discovery",
        http_status: Optional[int] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        request_payload: Optional[dict[str, Any]] = None,
        response_payload: Optional[dict[str, Any]] = None,
        latency_ms: Optional[int] = None,
    ) -> None:
        """Log a PDA agent call for audit trail."""
        repo = self.agent_call_log_repo
        if repo is None:
            return
        try:
            await repo.create_log(
                log_id=str(uuid.uuid4()),
                workflow_run_id=workflow_run_id,
                user_id=user_id,
                chat_id=chat_id,
                target_service=target_service,
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
                retry_of_log_id=None,
            )
        except (aiomysql.Error, RuntimeError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("pda_call_log_write_failed", operation=operation, error=str(exc))

    async def _handle_scholarship_search(
        self,
        *,
        user_id: str,
        chat_id: str,
        content: str,
        workflow_run_id: str,
        gate: dict[str, Any],
    ) -> dict[str, Any]:
        """Call Scholarship Discovery Agent to search scholarships.

        Uses SDA's /api/v1/scholarships/search endpoint which filters
        scholarships based on student profile and optional program links.
        Falls back to a helpful message if the SDA call fails.
        """
        started_at = time.perf_counter()

        # Get profile data and transform it for SDA's expected format
        raw_profile = await self._get_student_profile_for_agents(user_id, gate)
        student_profile = self._transform_profile_for_sda(raw_profile)

        # Extract program context from user's message
        program_context = await self._extract_program_context_for_scholarships(
            content=content,
            user_id=user_id,
            chat_id=chat_id,
            workflow_run_id=workflow_run_id,
        )

        program_ids = program_context.get("program_ids", [])
        provider = program_context.get("provider")
        unresolved_context = program_context.get("unresolved_context")

        # If we have unresolved program mentions, enrich the profile with that context
        if unresolved_context and student_profile:
            if unresolved_context.get("field") and not student_profile.get("field_of_study"):
                student_profile["field_of_study"] = unresolved_context["field"]
            if unresolved_context.get("degree_type") and not student_profile.get("degree_type"):
                student_profile["degree_type"] = unresolved_context["degree_type"]

        try:
            result = await self.scholarship_discovery_client.search_scholarships(
                user_id=user_id,
                student_profile=student_profile if student_profile else None,
                program_ids=program_ids if program_ids else None,
                provider=provider,
                trace_id=workflow_run_id,
                session_id=chat_id,
            )

            await self._record_scholarship_discovery_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="scholarship_search",
                request_method="POST",
                request_path="/api/v1/scholarships/search",
                call_status="success",
                request_payload={
                    "student_profile": student_profile,
                    "program_ids": program_ids,
                    "provider": provider,
                    "program_context": program_context,
                },
                response_payload=self._truncate_scholarship_response_for_logging(result),
                latency_ms=self._elapsed_ms(started_at),
            )

            formatted_answer = self._format_scholarship_search_response(
                result,
                program_context=program_context,
            )
            # Extract agent_reasoning from SDA response
            agent_reasoning = result.get("agent_reasoning")
            return {
                "answer": formatted_answer,
                "agent_reasoning": agent_reasoning,
                "source": "scholarship_discovery",
                "dashboard_items": self._build_scholarship_dashboard_items_from_chat_result(result),
            }

        except AgentClientError as exc:
            await self._record_scholarship_discovery_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="scholarship_search",
                request_method="POST",
                request_path="/api/v1/scholarships/search",
                call_status="failed",
                http_status=exc.status_code,
                error_code="agent_client_error",
                error_message=str(exc),
                request_payload={
                    "student_profile": student_profile,
                    "program_ids": program_ids,
                    "provider": provider,
                },
                latency_ms=self._elapsed_ms(started_at),
            )
            logger.error(
                "scholarship_discovery_call_failed",
                user_id=user_id,
                chat_id=chat_id,
                status_code=exc.status_code,
                error=str(exc),
            )
            return {
                "answer": (
                    "I tried to search scholarships for you, but the scholarship discovery "
                    "service encountered an issue. Please try again in a moment."
                ),
                "agent_reasoning": None,
                "source": "scholarship_discovery",
                "dashboard_items": [],
            }
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "scholarship_discovery_unexpected_error",
                user_id=user_id,
                chat_id=chat_id,
                error=str(exc),
            )
            return {
                "answer": "I ran into an unexpected issue while searching for scholarships. Please try again shortly.",
                "agent_reasoning": None,
                "source": "scholarship_discovery",
                "dashboard_items": [],
            }

    async def _handle_eligibility_check(
        self,
        *,
        user_id: str,
        chat_id: str,
        content: str,
        workflow_run_id: str,
        gate: dict[str, Any],
        is_clarification_reply: bool = False,
        pending_eligibility_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Call the Eligibility Engine to evaluate the user against a program or scholarship.

        Tries to resolve entity_type and entity_id from the user message.
        If resolution fails, returns a clarifying follow-up question instead of calling the engine.

        Returns:
            Dict with 'answer' (str) and optional 'agent_reasoning' (dict).
        """
        started_at = time.perf_counter()
        _ = gate

        context_entity_type = None
        if isinstance(pending_eligibility_context, dict):
            candidate = str(pending_eligibility_context.get("entity_type") or "").strip().lower()
            if candidate in {"program", "scholarship"}:
                context_entity_type = candidate

        primary_entity_type = (
            context_entity_type
            if is_clarification_reply and context_entity_type
            else self._detect_entity_type_for_eligibility(content)
        )
        secondary_entity_type = "scholarship" if primary_entity_type == "program" else "program"

        # Resolve entity from the primary type first; fall back to secondary if unresolved.
        primary_entity_id, primary_entity_name = await self._resolve_entity_for_eligibility(
            content=content,
            entity_type=primary_entity_type,
            user_id=user_id,
            chat_id=chat_id,
            workflow_run_id=workflow_run_id,
            is_clarification_reply=is_clarification_reply,
            pending_eligibility_context=pending_eligibility_context,
        )

        entity_type = primary_entity_type
        entity_id = primary_entity_id
        entity_name = primary_entity_name

        # If primary resolution failed and we're not in a clarification flow with explicit entity type,
        # attempt secondary entity type as fallback (e.g., user said "am I eligible" without specifying)
        should_fallback_to_secondary = not entity_id and not (
            is_clarification_reply and context_entity_type is not None
        )

        if should_fallback_to_secondary:
            secondary_entity_id, secondary_entity_name = await self._resolve_entity_for_eligibility(
                content=content,
                entity_type=secondary_entity_type,
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                is_clarification_reply=is_clarification_reply,
                pending_eligibility_context=pending_eligibility_context,
            )
            if secondary_entity_id:
                entity_type = secondary_entity_type
                entity_id = secondary_entity_id
                entity_name = secondary_entity_name

        if not entity_id:
            if entity_type == "program" and is_clarification_reply and self._is_generic_program_title_hint(content):
                clarification_prompt = (
                    "Thanks, but that title is still too broad. "
                    "Please include the university and full program name "
                    '(for example: "NUS Master of Science in Computer Science"), '
                    "or paste the program ID directly."
                )
            elif is_clarification_reply:
                clarification_prompt = self._eligibility_unresolved_after_clarification_message(primary_entity_type)
            else:
                clarification_prompt = self._eligibility_clarification_message(primary_entity_type)
            return {
                "answer": clarification_prompt,
                "agent_reasoning": None,
                "source": "orchestrator",
                "pending_intent": "eligibility_check",
                "pending_eligibility_context": self._build_pending_eligibility_context(
                    content=content,
                    entity_type=primary_entity_type,
                    existing_context=pending_eligibility_context,
                ),
            }

        try:
            result = await self.eligibility_service.evaluate(
                EligibilityEvaluationInput(
                    user_id=user_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    include_attribution=True,
                ),
                trace_id=workflow_run_id,
            )

            await self._record_eligibility_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="eligibility_check",
                request_method="POST",
                request_path="/matching/evaluate",
                call_status="success",
                request_payload={
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "entity_name": entity_name,
                },
                response_payload=self._truncate_response_for_logging(result),
                latency_ms=self._elapsed_ms(started_at),
            )

            result_payload = result.get("data") if isinstance(result.get("data"), dict) else result
            answer = self._format_eligibility_response(
                result=result_payload,
                entity_type=entity_type,
                entity_name=entity_name,
            )
            return {
                "answer": answer,
                "agent_reasoning": result_payload.get("agent_reasoning"),
                "source": "eligibility_engine",
            }

        except HTTPException as exc:
            await self._record_eligibility_call(
                user_id=user_id,
                chat_id=chat_id,
                workflow_run_id=workflow_run_id,
                operation="eligibility_check",
                request_method="POST",
                request_path="/matching/evaluate",
                call_status="failed",
                http_status=exc.status_code,
                error_code="http_exception",
                error_message=str(exc.detail),
                request_payload={"entity_type": entity_type, "entity_id": entity_id},
                latency_ms=self._elapsed_ms(started_at),
            )
            logger.error(
                "eligibility_check_http_error",
                user_id=user_id,
                chat_id=chat_id,
                entity_type=entity_type,
                entity_id=entity_id,
                status_code=exc.status_code,
                error=str(exc.detail),
            )
            if exc.status_code in (
                status.HTTP_424_FAILED_DEPENDENCY,
                status.HTTP_502_BAD_GATEWAY,
            ):
                detail = str(exc.detail or "").strip()
                lowered_detail = detail.lower()

                if "student profile" in lowered_detail:
                    missing_fields: list[str] = []
                    try:
                        readiness = await self.profile_gate_service.evaluate_gate(
                            user_id,
                            intent="eligibility_check",
                            chat_id=chat_id,
                            workflow_run_id=workflow_run_id,
                        )
                        missing_fields = _as_string_list(
                            readiness.get("missing_required_fields") or readiness.get("missing_fields") or []
                        )
                    except (HTTPException, AgentClientError, aiomysql.Error, RuntimeError, ValueError, TypeError):
                        missing_fields = []

                    if missing_fields:
                        labels = [self._format_profile_field_label(field) for field in missing_fields if field]
                        missing_text = self._join_humanized_labels(labels)
                        return {
                            "answer": (
                                "I couldn't check your eligibility yet because your profile is incomplete. "
                                f"Please share your {missing_text}, then try again."
                            ),
                            "agent_reasoning": None,
                            "source": "eligibility_engine",
                        }

                    return {
                        "answer": (
                            "I couldn't check your eligibility yet because your student profile isn't ready. "
                            "Please complete your profile details and try again."
                        ),
                        "agent_reasoning": None,
                        "source": "eligibility_engine",
                    }

                if "program details" in lowered_detail or "scholarship details" in lowered_detail:
                    return {
                        "answer": (
                            "I couldn't fetch the latest details for that program or scholarship just now. "
                            "Please try again in a moment, or provide the exact name/ID to retry."
                        ),
                        "agent_reasoning": None,
                        "source": "eligibility_engine",
                    }

                return {
                    "answer": (
                        "I wasn't able to check your eligibility right now — "
                        "a required dependency couldn't be fetched. "
                        "Please try again in a moment."
                    ),
                    "agent_reasoning": None,
                    "source": "eligibility_engine",
                }
            return {
                "answer": (
                    "I tried to check your eligibility but the eligibility service encountered an issue. "
                    "Please try again in a moment."
                ),
                "agent_reasoning": None,
                "source": "eligibility_engine",
            }

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "eligibility_check_unexpected_error",
                user_id=user_id,
                chat_id=chat_id,
                error=str(exc),
            )
            return {
                "answer": "I ran into an unexpected issue while checking your eligibility. Please try again shortly.",
                "agent_reasoning": None,
                "source": "eligibility_engine",
            }

    @staticmethod
    def _detect_entity_type_for_eligibility(content: str) -> str:
        """Return 'scholarship' or 'program' based on message keywords."""
        lowered = content.lower()
        scholarship_keywords = {"scholarship", "grant", "bursary", "fellowship", "award"}
        if any(kw in lowered for kw in scholarship_keywords):
            return "scholarship"
        return "program"

    async def _resolve_entity_for_eligibility(  # pylint: disable=too-many-nested-blocks
        self,
        *,
        content: str,
        entity_type: str,
        user_id: str,
        chat_id: str,
        workflow_run_id: str,
        is_clarification_reply: bool = False,
        pending_eligibility_context: Optional[dict[str, Any]] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Extract or resolve entity_id from the user message.

        Returns (entity_id, entity_name). entity_id is None when unresolvable.
        Strategy:
          1. If message contains a bare UUID, use it.
          2. Otherwise query PDA/SDA for a name-based match.
          3. When is_clarification_reply is True, pick the best (first) result even if
             multiple are returned.
          4. When is_clarification_reply is False, only auto-select if unambiguous (exactly 1).
        """
        uuid_re = re.compile(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
            re.IGNORECASE,
        )
        uuid_match = uuid_re.search(content)
        if uuid_match:
            return uuid_match.group(0), None

        if entity_type == "program" and is_clarification_reply and self._is_generic_program_title_hint(content):
            return None, None

        try:
            if entity_type == "program":
                program_queries = self._build_program_entity_queries(content)
                for query in program_queries:
                    search_result = await self.program_discovery_client.search_programs(
                        query=query,
                        page_size=5,
                        user_id=user_id,
                        trace_id=workflow_run_id,
                        session_id=chat_id,
                    )
                    items = (
                        search_result.get("data") or search_result.get("programs") or search_result.get("items") or []
                    )
                    if items and isinstance(items[0], dict):
                        if is_clarification_reply or len(items) == 1:
                            item = items[0]
                            return str(item.get("id") or ""), item.get("name") or item.get("program_name")

                # Fallback: if user includes institution in free text (e.g. "NUS Master of Science"),
                # first resolve institution, then search programs scoped to that institution.
                institution_hint, title_hint = self._extract_program_institution_and_title_hint(content)
                if not institution_hint and isinstance(pending_eligibility_context, dict):
                    institution_hint = str(pending_eligibility_context.get("institution_hint") or "").strip() or None
                    if not title_hint:
                        title_hint = str(pending_eligibility_context.get("program_title_hint") or "").strip() or None
                if institution_hint:
                    inst_result = await self.program_discovery_client.search_institutions(
                        query=institution_hint,
                        page_size=3,
                        user_id=user_id,
                        trace_id=workflow_run_id,
                        session_id=chat_id,
                    )
                    institutions = (
                        inst_result.get("data") or inst_result.get("institutions") or inst_result.get("items") or []
                    )
                    if institutions and isinstance(institutions[0], dict):
                        institution_id = str(institutions[0].get("id") or "")
                        if institution_id:
                            scoped_seed = title_hint or self._normalize_program_entity_query(content)
                            scoped_queries = self._build_program_entity_queries(scoped_seed)
                            for scoped_query in scoped_queries:
                                scoped_result = await self.program_discovery_client.search_programs(
                                    query=scoped_query,
                                    institution_id=institution_id,
                                    page_size=5,
                                    user_id=user_id,
                                    trace_id=workflow_run_id,
                                    session_id=chat_id,
                                )
                                scoped_items = (
                                    scoped_result.get("data")
                                    or scoped_result.get("programs")
                                    or scoped_result.get("items")
                                    or []
                                )
                                if scoped_items and isinstance(scoped_items[0], dict):
                                    if is_clarification_reply or len(scoped_items) == 1:
                                        item = scoped_items[0]
                                        return str(item.get("id") or ""), item.get("name") or item.get("program_name")
            else:
                search_result = await self.scholarship_discovery_client.search_scholarships(
                    user_id=user_id,
                    trace_id=workflow_run_id,
                    session_id=chat_id,
                )
                items = search_result.get("data") or []
                if items and isinstance(items[0], dict):
                    # For clarification replies, filter items by name match to avoid selecting
                    # an unrelated scholarship when user provides a specific name
                    if is_clarification_reply:
                        content_lower = content.lower()
                        matched = [
                            item
                            for item in items
                            if isinstance(item, dict)
                            and (
                                content_lower in (item.get("name") or "").lower()
                                or content_lower in (item.get("title") or "").lower()
                            )
                        ]
                        if len(matched) == 1:
                            return str(matched[0].get("id") or ""), matched[0].get("name") or matched[0].get("title")
                        # If no exact match found but only one result, use it
                        if not matched and len(items) == 1:
                            item = items[0]
                            return str(item.get("id") or ""), item.get("name") or item.get("title")
                    elif len(items) == 1:
                        item = items[0]
                        return str(item.get("id") or ""), item.get("name") or item.get("title")
        except (AgentClientError, HTTPException) as exc:
            logger.warning(
                "eligibility_entity_resolution_failed",
                entity_type=entity_type,
                user_id=user_id,
                error=str(exc),
            )

        return None, None

    @staticmethod
    def _is_generic_program_title_hint(content: str) -> bool:
        """Return True when the reply is too generic to safely pick a single program."""
        generic_titles = {
            "master",
            "masters",
            "master of science",
            "msc",
            "m.sc",
            "ms",
            "bachelor",
            "bachelors",
            "bachelor of science",
            "phd",
            "doctorate",
        }

        normalized = re.sub(r"\s+", " ", (content or "").strip().lower())
        if not normalized:
            return True
        if normalized in generic_titles:
            return True

        institution_hint, title_hint = ChatService._extract_program_institution_and_title_hint(content)
        if institution_hint and title_hint:
            normalized_title = re.sub(r"\s+", " ", title_hint.strip().lower())
            if normalized_title in generic_titles:
                return True

        return False

    @classmethod
    def _build_pending_eligibility_context(
        cls,
        *,
        content: str,
        entity_type: str,
        existing_context: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """Capture lightweight hints to resolve eligibility entity on the next user turn.

        Always persists entity_type so follow-up turns retain context for both programs
        and scholarships. For programs, also extracts institution/title hints.
        """
        merged: dict[str, Any] = {}
        if isinstance(existing_context, dict):
            merged.update(existing_context)

        # Always persist entity_type so scholarship flows retain context
        merged["entity_type"] = entity_type

        if entity_type == "program":
            institution_hint, title_hint = cls._extract_program_institution_and_title_hint(content)
            if not institution_hint:
                institution_hint = cls._extract_institution_hint_from_text(content)
            if institution_hint:
                merged["institution_hint"] = institution_hint
            if title_hint:
                merged["program_title_hint"] = title_hint
        elif entity_type == "scholarship":
            # Extract scholarship name hint from content for better disambiguation
            scholarship_hint = cls._extract_scholarship_name_hint(content)
            if scholarship_hint:
                merged["scholarship_name_hint"] = scholarship_hint

        return merged or None

    @staticmethod
    def _extract_scholarship_name_hint(content: str) -> Optional[str]:
        """Extract likely scholarship name from content for disambiguation."""
        text = re.sub(r"\s+", " ", (content or "").strip())
        if not text:
            return None
        # Remove common eligibility intent scaffolding
        cleaned = re.sub(
            r"^(check|tell|find|show|assess|evaluate)?\s*(my\s*)?"
            r"(eligibility|eligible|qualification|qualify)\s*(for|to)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"^[\-:\u2014\s]+", "", cleaned).strip()
        return cleaned if cleaned else None

    @staticmethod
    def _normalize_program_entity_query(content: str) -> str:
        """Strip intent scaffolding so PDA search gets a cleaner program title query."""
        cleaned = re.sub(r"\s+", " ", (content or "").strip())
        cleaned = re.sub(
            (
                r"^(check|tell|find|show|assess|evaluate)?\s*(my\s*)?"
                r"(eligibility|eligible|qualification|qualify)\s*(for|to)?\s*"
            ),
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"^[\-:\u2014\s]+", "", cleaned).strip()
        return cleaned or content

    @staticmethod
    def _extract_institution_hint_from_text(content: str) -> Optional[str]:
        """Extract likely institution acronym from free text (e.g., 'for MIT' → 'MIT')."""
        text = re.sub(r"\s+", " ", (content or "").strip())
        if not text:
            return None
        acronyms = re.findall(r"\b[A-Z]{2,10}\b", text)
        if acronyms:
            return acronyms[-1]
        return None

    @classmethod
    def _build_program_entity_queries(cls, content: str) -> list[str]:
        """Build a small query set to improve PDA recall for free-form program names."""
        primary = cls._normalize_program_entity_query(content)
        queries = [primary]
        if primary.lower() != (content or "").strip().lower():
            queries.append((content or "").strip())

        deduped: list[str] = []
        seen: set[str] = set()
        for query in queries:
            normalized_key = re.sub(r"\s+", " ", (query or "").strip().lower())
            if not normalized_key or normalized_key in seen:
                continue
            seen.add(normalized_key)
            deduped.append(query)
        return deduped

    @staticmethod
    def _extract_program_institution_and_title_hint(content: str) -> tuple[Optional[str], Optional[str]]:
        """Extract lightweight institution/title hints from text like 'NUS Master of Science'."""
        normalized = re.sub(r"\s+", " ", (content or "").strip())
        if not normalized:
            return None, None

        # Common abbreviation-first pattern: "NUS Master of Science"
        m = re.match(r"^([A-Za-z]{2,10})\s*(?:[-:|]\s*)?(.+)$", normalized)
        if m:
            org = m.group(1)
            rest = re.sub(r"^[\-:|\s]+", "", m.group(2)).strip()
            degree_like = re.match(
                r"^(mscs|msc|m\.sc|ms|phd|mba|llm|meng|mfin|mpp|mph|bsc|bs|ba)\b",
                rest,
                flags=re.IGNORECASE,
            )
            if org.isupper() and (len(rest.split()) >= 2 or degree_like):
                return org, rest

        # Phrase pattern: "<institution> <master|msc|phd|bachelor ...>"
        m2 = re.match(
            r"^(.+?)\s+(master|masters|master's|m\.sc|msc|ms|phd|doctorate|bachelor|b\.sc|bs|ba)\b(.*)$",
            normalized,
            flags=re.IGNORECASE,
        )
        if m2:
            institution = m2.group(1).strip()
            degree_head = m2.group(2).strip()
            degree_tail = (m2.group(3) or "").strip()
            title = f"{degree_head} {degree_tail}".strip()
            return institution, title

        return None, None

    @staticmethod
    def _format_eligibility_response(
        *,
        result: dict[str, Any],
        entity_type: str,
        entity_name: Optional[str],
    ) -> str:
        """Format the eligibility engine response into a human-readable answer."""
        match_result = result.get("match_result") or {}
        raw_score = match_result.get("match_score")
        try:
            score = float(raw_score) if raw_score is not None else None
        except (TypeError, ValueError):
            score = None
        confidence = str(match_result.get("confidence_level") or "").lower()
        breakdown = match_result.get("score_breakdown") or {}

        entity_label = entity_name or entity_type

        if score is None:
            return (
                f"I ran the eligibility check for {entity_label}, "
                "but wasn't able to produce a score. Please try again."
            )

        if score >= 70:
            verdict = "You appear to be a strong match"
            qualifier = "high" if confidence == "high" else "good"
        elif score >= 40:
            verdict = "You may partially qualify"
            qualifier = "moderate"
        else:
            verdict = "You appear to be below the typical threshold"
            qualifier = "low"

        lines: list[str] = [
            f"**Eligibility Result for {entity_label}**",
            "",
            f"{verdict} \u2014 score: **{score}/100** ({qualifier} confidence).",
        ]

        attribution = result.get("attribution_report") or {}
        narrative = attribution.get("narrative") or attribution.get("summary")
        if narrative and isinstance(narrative, str):
            lines += ["", narrative.strip()]

        if breakdown:
            significant = {k: v for k, v in breakdown.items() if isinstance(v, (int, float)) and v > 0}
            if significant:
                top = sorted(significant.items(), key=lambda x: x[1], reverse=True)[:3]
                breakdown_text = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in top)
                lines += ["", f"Top scoring factors: {breakdown_text}."]

        lines += ["", "Would you like to review the full breakdown or explore other opportunities?"]
        return "\n".join(lines)

    @staticmethod
    def _eligibility_clarification_message(entity_type: str) -> str:
        """Return a follow-up question when the target entity cannot be resolved."""
        entity_label = "scholarship" if entity_type == "scholarship" else "program"
        return (
            f"I'd like to check your eligibility for that {entity_label}, "
            "but I need a bit more detail. "
            f"Could you share the name or ID of the specific {entity_label} you'd like to evaluate? "
            f'For example: "Check my eligibility for NUS Master of Computing" '
            "or paste the program ID directly."
        )

    @staticmethod
    def _eligibility_unresolved_after_clarification_message(entity_type: str) -> str:
        """Return a follow-up when clarification reply is specific but no exact entity match was found."""
        entity_label = "scholarship" if entity_type == "scholarship" else "program"
        return (
            f"Thanks, I still couldn't find an exact {entity_label} match in our catalog. "
            f"Please share the exact official {entity_label} name or paste the {entity_label} ID directly. "
            "If you have a program URL, you can share that too."
        )

    async def _record_eligibility_call(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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
    ) -> None:
        """Log an eligibility-engine agent call for audit trail."""
        repo = self.agent_call_log_repo
        if repo is None:
            return
        try:
            await repo.create_log(
                log_id=str(uuid.uuid4()),
                workflow_run_id=workflow_run_id,
                user_id=user_id,
                chat_id=chat_id,
                target_service="eligibility-engine",
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
                retry_of_log_id=None,
            )
        except (aiomysql.Error, RuntimeError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("eligibility_call_log_write_failed", operation=operation, error=str(exc))

    async def _extract_program_context_for_scholarships(
        self,
        content: str,
        user_id: str,
        chat_id: str,  # pylint: disable=unused-argument  # Reserved for future conversation context
        workflow_run_id: str,
    ) -> dict[str, Any]:
        """Extract program context from user's scholarship query.

        This method:
        1. Extracts university/program/field mentions from the message
        2. Extracts scholarship provider mentions (Fulbright, etc.)
        3. Searches PDA for matching programs if university is mentioned
        4. Returns program_ids if found, or unresolved context if not

        Examples:
        - "scholarships for MIT computer science" → search PDA for MIT CS programs
        - "Fulbright scholarships for engineering" → provider=Fulbright, field=engineering
        - "funding for Stanford MBA" → search PDA for Stanford MBA programs
        """
        context: dict[str, Any] = {
            "program_ids": [],
            "programs": [],
            "provider": None,
            "mentioned_university": None,
            "mentioned_field": None,
            "mentioned_degree": None,
            "unresolved_context": None,
        }

        content_lower = content.lower()

        # 1. Extract scholarship provider mentions
        provider_keywords = {
            "fulbright": "Fulbright",
            "gates cambridge": "Gates Cambridge",
            "gates": "Gates Foundation",
            "chevening": "Chevening",
            "erasmus": "Erasmus",
            "commonwealth": "Commonwealth",
            "rhodes": "Rhodes",
            "marshall": "Marshall",
            "schwarzman": "Schwarzman",
            "knight-hennessy": "Knight-Hennessy",
        }
        for keyword, provider_name in provider_keywords.items():
            if keyword in content_lower:
                context["provider"] = provider_name
                logger.info("scholarship_provider_extracted", provider=provider_name, user_id=user_id)
                break

        # 2. Extract university mentions and infer country
        university_patterns = self._get_university_patterns()
        university_country_map = self._get_university_country_map()
        mentioned_university = None
        inferred_country = None
        for pattern, university_name in university_patterns.items():
            if pattern in content_lower:
                mentioned_university = university_name
                context["mentioned_university"] = university_name
                # Infer country from university
                inferred_country = university_country_map.get(university_name)
                if inferred_country:
                    context["inferred_country"] = inferred_country
                    logger.info(
                        "country_inferred_from_university",
                        university=university_name,
                        country=inferred_country,
                        user_id=user_id,
                    )
                # If no external provider (Fulbright etc) was found, use university as provider
                # This allows "NUS scholarships" to find scholarships where provider="National University of Singapore"
                if not context["provider"]:
                    context["provider"] = university_name
                    logger.info(
                        "university_used_as_scholarship_provider",
                        university=university_name,
                        user_id=user_id,
                    )
                break

        # 3. Extract field of study mentions
        field_patterns = {
            "computer science": "Computer Science",
            "cs program": "Computer Science",
            "engineering": "Engineering",
            "business": "Business",
            "mba": "Business Administration",
            "medicine": "Medicine",
            "law": "Law",
            "economics": "Economics",
            "data science": "Data Science",
            "artificial intelligence": "Artificial Intelligence",
            "machine learning": "Machine Learning",
            "physics": "Physics",
            "mathematics": "Mathematics",
            "biology": "Biology",
            "chemistry": "Chemistry",
            "psychology": "Psychology",
        }
        for pattern, field_name in field_patterns.items():
            if pattern in content_lower:
                context["mentioned_field"] = field_name
                break

        # 4. Extract degree type mentions
        degree_patterns = {
            "phd": "phd",
            "doctorate": "phd",
            "doctoral": "phd",
            "master": "master",
            "masters": "master",
            "msc": "master",
            "mba": "master",
            "bachelor": "bachelor",
            "undergraduate": "bachelor",
            "undergrad": "bachelor",
        }
        for pattern, degree_type in degree_patterns.items():
            if pattern in content_lower:
                context["mentioned_degree"] = degree_type
                break

        # 5. If university is mentioned, search PDA for matching programs
        if mentioned_university:
            pda_programs = await self._search_pda_for_programs(
                university_name=mentioned_university,
                field=context.get("mentioned_field"),
                degree_type=context.get("mentioned_degree"),
                user_id=user_id,
                workflow_run_id=workflow_run_id,
            )

            if pda_programs:
                context["program_ids"] = [p["id"] for p in pda_programs if p.get("id")]
                context["programs"] = pda_programs
                logger.info(
                    "programs_found_for_scholarship_search",
                    user_id=user_id,
                    university=mentioned_university,
                    program_count=len(pda_programs),
                    program_ids=context["program_ids"][:5],
                )
            else:
                # Programs not found in PDA, but we have context to pass
                context["unresolved_context"] = {
                    "university_name": mentioned_university,
                    "field": context.get("mentioned_field"),
                    "degree_type": context.get("mentioned_degree"),
                }
                logger.info(
                    "programs_not_found_using_unresolved_context",
                    user_id=user_id,
                    university=mentioned_university,
                    field=context.get("mentioned_field"),
                )

        # 6. Even without university, if field/degree mentioned, set as unresolved context
        elif context.get("mentioned_field") or context.get("mentioned_degree"):
            context["unresolved_context"] = {
                "field": context.get("mentioned_field"),
                "degree_type": context.get("mentioned_degree"),
            }

        return context

    async def _search_pda_for_programs(
        self,
        university_name: str,
        field: Optional[str],
        degree_type: Optional[str],
        user_id: str,
        workflow_run_id: str,
    ) -> list[dict[str, Any]]:
        """Search PDA for programs matching the university/field/degree.

        Returns list of program dicts with id, name, institution, field, degree_type, country.
        """
        try:
            # First, search for the institution
            institutions_result = await self.program_discovery_client.search_institutions(
                query=university_name,
                page_size=5,
                user_id=user_id,
                trace_id=workflow_run_id,
            )

            institution_id = None
            institution_data = None
            if isinstance(institutions_result, dict):
                items = institutions_result.get("items") or institutions_result.get("data", {}).get("items", [])
                if items and isinstance(items, list) and len(items) > 0:
                    institution_data = items[0]
                    institution_id = institution_data.get("id")

            if not institution_id:
                logger.info(
                    "institution_not_found_in_pda",
                    university_name=university_name,
                    user_id=user_id,
                )
                return []

            # Search for programs at this institution
            programs_result = await self.program_discovery_client.search_programs(
                institution_id=institution_id,
                field=field,
                degree_type=degree_type,
                page_size=10,
                user_id=user_id,
                trace_id=workflow_run_id,
            )

            programs = []
            if isinstance(programs_result, dict):
                items = programs_result.get("items") or programs_result.get("data", {}).get("items", [])
                if items and isinstance(items, list):
                    for program in items[:10]:
                        programs.append(
                            {
                                "id": program.get("id"),
                                "name": program.get("name"),
                                "institution_name": (
                                    program.get("institution", {}).get("name") or institution_data.get("name")
                                    if institution_data
                                    else None
                                ),
                                "field": program.get("field"),
                                "degree_type": program.get("degree_type"),
                                "country": (
                                    program.get("institution", {}).get("country") or institution_data.get("country")
                                    if institution_data
                                    else None
                                ),
                            }
                        )

            return programs

        except AgentClientError as exc:
            logger.warning(
                "pda_search_for_scholarship_context_failed",
                university_name=university_name,
                error=str(exc),
                user_id=user_id,
            )
            return []
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "pda_search_unexpected_error",
                university_name=university_name,
                error=str(exc),
                user_id=user_id,
            )
            return []

    @staticmethod
    def _get_university_patterns() -> dict[str, str]:
        """Return mapping of search patterns to canonical university names."""
        return {
            # US Universities
            "mit": "Massachusetts Institute of Technology",
            "massachusetts institute of technology": "Massachusetts Institute of Technology",
            "stanford": "Stanford University",
            "harvard": "Harvard University",
            "yale": "Yale University",
            "princeton": "Princeton University",
            "columbia": "Columbia University",
            "berkeley": "University of California, Berkeley",
            "uc berkeley": "University of California, Berkeley",
            "ucla": "University of California, Los Angeles",
            "caltech": "California Institute of Technology",
            "carnegie mellon": "Carnegie Mellon University",
            "cmu": "Carnegie Mellon University",
            "nyu": "New York University",
            "upenn": "University of Pennsylvania",
            "penn": "University of Pennsylvania",
            "cornell": "Cornell University",
            "duke": "Duke University",
            "northwestern": "Northwestern University",
            "uchicago": "University of Chicago",
            "johns hopkins": "Johns Hopkins University",
            "georgia tech": "Georgia Institute of Technology",
            # UK Universities
            "oxford": "University of Oxford",
            "cambridge": "University of Cambridge",
            "imperial": "Imperial College London",
            "imperial college": "Imperial College London",
            "ucl": "University College London",
            "lse": "London School of Economics",
            "edinburgh": "University of Edinburgh",
            "manchester": "University of Manchester",
            "kings college": "King's College London",
            "kcl": "King's College London",
            # Singapore Universities
            "nus": "National University of Singapore",
            "ntu": "Nanyang Technological University",
            "nanyang": "Nanyang Technological University",
            "smu": "Singapore Management University",
            "sutd": "Singapore University of Technology and Design",
            # Other
            "eth zurich": "ETH Zurich",
            "eth": "ETH Zurich",
            "epfl": "EPFL",
            "toronto": "University of Toronto",
            "mcgill": "McGill University",
            "melbourne": "University of Melbourne",
            "sydney": "University of Sydney",
            "anu": "Australian National University",
            "tsinghua": "Tsinghua University",
            "peking": "Peking University",
            "tokyo": "University of Tokyo",
            "kyoto": "Kyoto University",
            "seoul national": "Seoul National University",
            "kaist": "KAIST",
        }

    @staticmethod
    def _get_university_country_map() -> dict[str, str]:
        """Return mapping of canonical university names to their countries."""
        return {
            # US Universities
            "Massachusetts Institute of Technology": "United States",
            "Stanford University": "United States",
            "Harvard University": "United States",
            "Yale University": "United States",
            "Princeton University": "United States",
            "Columbia University": "United States",
            "University of California, Berkeley": "United States",
            "University of California, Los Angeles": "United States",
            "California Institute of Technology": "United States",
            "Carnegie Mellon University": "United States",
            "New York University": "United States",
            "University of Pennsylvania": "United States",
            "Cornell University": "United States",
            "Duke University": "United States",
            "Northwestern University": "United States",
            "University of Chicago": "United States",
            "Johns Hopkins University": "United States",
            "Georgia Institute of Technology": "United States",
            # UK Universities
            "University of Oxford": "United Kingdom",
            "University of Cambridge": "United Kingdom",
            "Imperial College London": "United Kingdom",
            "University College London": "United Kingdom",
            "London School of Economics": "United Kingdom",
            "University of Edinburgh": "United Kingdom",
            "University of Manchester": "United Kingdom",
            "King's College London": "United Kingdom",
            # Singapore Universities
            "National University of Singapore": "Singapore",
            "Nanyang Technological University": "Singapore",
            "Singapore Management University": "Singapore",
            "Singapore University of Technology and Design": "Singapore",
            # Switzerland
            "ETH Zurich": "Switzerland",
            "EPFL": "Switzerland",
            # Canada
            "University of Toronto": "Canada",
            "McGill University": "Canada",
            # Australia
            "University of Melbourne": "Australia",
            "University of Sydney": "Australia",
            "Australian National University": "Australia",
            # China
            "Tsinghua University": "China",
            "Peking University": "China",
            # Japan
            "University of Tokyo": "Japan",
            "Kyoto University": "Japan",
            # South Korea
            "Seoul National University": "South Korea",
            "KAIST": "South Korea",
        }

    async def _fetch_profile_from_spa(
        self,
        profile_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        """Fetch full profile from SPA and extract fields. Returns empty dict on failure."""
        try:
            response = await self.profile_gate_service.student_profile_client.get_profile(
                profile_id=profile_id,
                user_id=user_id,
            )
            if not isinstance(response, dict):
                return {}
            profile = response.get("data") if isinstance(response.get("data"), dict) else response
            if not isinstance(profile, dict):
                return {}
            fields = self._extract_profile_fields(profile)
            logger.info(
                "student_profile_fetched_for_agents",
                user_id=user_id,
                profile_id=profile_id,
                fields=list(fields.keys()),
            )
            return fields
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "student_profile_fetch_for_agents_failed",
                user_id=user_id,
                profile_id=profile_id,
                error=str(exc),
            )
            return {}

    async def _resolve_profile_id_from_status(self, user_id: str) -> Optional[str]:
        """Get profile_id from SPA status endpoint. Returns None on failure."""
        try:
            response = await self.profile_gate_service.student_profile_client.get_profile_status(
                user_id=user_id,
            )
            if not isinstance(response, dict):
                return None
            data = response.get("data") or response
            return data.get("profile_id") if isinstance(data, dict) else None
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("profile_id_resolution_failed", user_id=user_id, error=str(exc))
            return None

    async def _get_student_profile_for_agents(
        self,
        user_id: str,
        gate: dict[str, Any],
    ) -> dict[str, Any]:
        """Extract student profile data in the shape PDA and SDA expect.

        Always returns a dict (possibly partial). Merges data from:
        1. Gate profile_data (if available from prior profile gate evaluation)
        2. SPA full profile (fetched by profile_id from gate)
        3. Orchestrator's user table (basic user data as fallback)

        Architecture principle: Even incomplete profiles should be sent to agents.
        Agents handle partial data gracefully and can still provide value.
        """
        merged: dict[str, Any] = {}

        # 1. Try gate profile_data first (already fetched during profile gating)
        profile_data = gate.get("profile_data")
        if isinstance(profile_data, dict):
            merged.update(self._extract_profile_fields(profile_data))

        # 2. Fetch full profile from SPA if gate didn't have profile_data
        if not merged:
            profile_id = gate.get("profile_id")
            if not profile_id:
                profile_id = await self._resolve_profile_id_from_status(user_id)
            if profile_id:
                merged.update(await self._fetch_profile_from_spa(profile_id, user_id))

        # 3. Enrich with orchestrator user data (basic info that might not be in SPA yet)
        await self._enrich_profile_from_user_table(merged, user_id)

        # Filter out None and empty values to keep payload clean
        return {k: v for k, v in merged.items() if v is not None and v != "" and v != []}

    async def _enrich_profile_from_user_table(self, merged: dict[str, Any], user_id: str) -> None:
        """Enrich profile dict with data from orchestrator's user table."""
        try:
            pool = get_pool()
            if not pool:
                return
            user_repo = UserRepository(pool)
            user = await user_repo.get_by_id(user_id)
            if not isinstance(user, dict):
                return
            self._apply_user_enrichment(merged, user)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug("orchestrator_user_enrichment_failed", user_id=user_id, error=str(exc))

    @staticmethod
    def _apply_user_enrichment(merged: dict[str, Any], user: dict[str, Any]) -> None:
        """Apply user table fields to profile dict (mutates merged in place)."""
        if not merged.get("full_name"):
            first_name = (user.get("first_name") or "").strip()
            last_name = (user.get("last_name") or "").strip()
            full_name = " ".join(p for p in [first_name, last_name] if p).strip()
            if full_name:
                merged["full_name"] = full_name

        if not merged.get("email") and user.get("email"):
            merged["email"] = user["email"]

        if not merged.get("field_of_study") and user.get("interest"):
            merged["field_of_study"] = user["interest"]

        if not merged.get("profession") and user.get("profession"):
            merged["profession"] = user["profession"]

    @staticmethod
    def _extract_profile_fields(profile: dict[str, Any]) -> dict[str, Any]:
        """Extract and normalize profile fields from various source formats."""
        return {
            "gpa": profile.get("gpa"),
            "gpa_scale": profile.get("gpa_scale") or profile.get("gpaScale") or 4.0,
            "nationality": profile.get("nationality"),
            "field_of_study": (
                profile.get("field_of_study") or profile.get("intended_field_of_study") or profile.get("fieldOfStudy")
            ),
            "degree_type": (
                profile.get("degree_type") or profile.get("target_degree_level") or profile.get("targetDegreeLevel")
            ),
            "current_degree_level": (profile.get("current_degree_level") or profile.get("currentDegreeLevel")),
            "target_country": (
                profile.get("target_country") or profile.get("target_study_country") or profile.get("targetCountry")
            ),
            "work_experience_years": (profile.get("work_experience_years") or profile.get("workExperienceYears")),
            "research_interests": (profile.get("research_interests") or profile.get("researchInterests")),
            "skills": profile.get("skills"),
            "test_scores": profile.get("test_scores") or profile.get("testScores"),
            "full_name": profile.get("full_name") or profile.get("fullName"),
            "email": profile.get("email"),
            "enrollment_timeline": (profile.get("enrollment_timeline") or profile.get("enrollmentTimeline")),
        }

    @staticmethod
    def _transform_profile_for_sda(profile: dict[str, Any]) -> dict[str, Any]:
        """Transform profile to SDA's StudentProfileFilter expected shape.

        SDA expects: gpa, gpa_scale, nationality, field_of_study, degree_type, language_test
        """
        if not profile:
            return {}

        sda_profile: dict[str, Any] = {}

        # Direct mappings
        if profile.get("gpa") is not None:
            sda_profile["gpa"] = profile["gpa"]
        if profile.get("gpa_scale") is not None:
            sda_profile["gpa_scale"] = profile["gpa_scale"]
        if profile.get("nationality"):
            sda_profile["nationality"] = profile["nationality"]
        if profile.get("field_of_study"):
            sda_profile["field_of_study"] = profile["field_of_study"]
        if profile.get("degree_type"):
            sda_profile["degree_type"] = profile["degree_type"]

        # Transform test_scores to language_test
        test_scores = profile.get("test_scores")
        if isinstance(test_scores, dict):
            # Look for language proficiency tests
            for test_name in ["ielts", "toefl", "duolingo", "pte"]:
                score = test_scores.get(test_name)
                if score is not None:
                    sda_profile["language_test"] = f"{test_name.upper()}: {score}"
                    break

        return sda_profile

    def _format_scholarship_search_response(
        self,
        result: dict[str, Any],
        program_context: Optional[dict[str, Any]] = None,
    ) -> str:
        """Format SDA scholarship search response for the user."""
        if not isinstance(result, dict):
            return "I found some scholarship information but couldn't format it properly. Please try again."

        data = result.get("data") or []
        total = result.get("total", 0)
        program_context = program_context or {}

        # Build context description for the response
        context_parts = []
        if program_context.get("mentioned_university"):
            context_parts.append(program_context["mentioned_university"])
        if program_context.get("mentioned_field"):
            context_parts.append(program_context["mentioned_field"])
        # Only add provider if it's different from the university (to avoid duplication)
        if program_context.get("provider") and program_context.get("provider") != program_context.get(
            "mentioned_university"
        ):
            context_parts.append(program_context["provider"])

        context_desc = " ".join(context_parts) if context_parts else "your profile"

        if not data:
            # Build a helpful no-results message with context
            no_results_msg = f"I searched for scholarships matching {context_desc} but didn't find any results."

            if program_context.get("unresolved_context"):
                unresolved = program_context["unresolved_context"]
                if unresolved.get("university_name"):
                    no_results_msg += (
                        f"\n\nNote: I couldn't find **{unresolved['university_name']}** in our program database. "
                        "The scholarship search was based on your profile instead."
                    )

            no_results_msg += (
                "\n\nThis could be because:\n"
                "• Your profile is still incomplete\n"
                "• The search criteria are too specific\n"
                "• We're still building our scholarship database\n\n"
                "Try broadening your search or completing more of your profile."
            )
            return no_results_msg

        # Build the results header
        if program_context.get("program_ids"):
            programs = program_context.get("programs", [])
            if programs:
                # Deduplicate institution names while preserving order
                seen_names: set[str] = set()
                unique_names: list[str] = []
                for p in programs[:5]:
                    name = p.get("institution_name") or p.get("name")
                    if name and name not in seen_names:
                        seen_names.add(name)
                        unique_names.append(name)
                program_list = ", ".join(unique_names[:3]) if unique_names else None
                if program_list:
                    header = f"I found {total} scholarship{'s' if total != 1 else ''} linked to **{program_list}**:\n"
                else:
                    header = f"I found {total} scholarship{'s' if total != 1 else ''} for the programs you mentioned:\n"
            else:
                header = f"I found {total} scholarship{'s' if total != 1 else ''} for the programs you mentioned:\n"
        elif program_context.get("provider"):
            header = (
                f"I found {total} **{program_context['provider']}** scholarship{'s' if total != 1 else ''} "
                "matching your profile:\n"
            )
        elif program_context.get("mentioned_university"):
            header = (
                f"I found {total} scholarship{'s' if total != 1 else ''} "
                f"relevant to **{program_context['mentioned_university']}**:\n"
            )
        elif program_context.get("mentioned_field"):
            header = (
                f"I found {total} scholarship{'s' if total != 1 else ''} "
                f"for **{program_context['mentioned_field']}**:\n"
            )
        else:
            header = f"I found {total} scholarship{'s' if total != 1 else ''} matching your profile:\n"

        response_parts = [header]

        for i, scholarship in enumerate(data[:5], 1):
            name = scholarship.get("name", "Unnamed Scholarship")
            provider = scholarship.get("provider", "Unknown Provider")
            amount = scholarship.get("funding_amount")
            currency = scholarship.get("currency", "USD")
            deadline = scholarship.get("deadline")
            link_confidence = scholarship.get("link_confidence")

            funding_text = f" ({currency} {amount:,.0f})" if amount else ""
            deadline_text = f" — Deadline: {deadline}" if deadline else ""
            confidence_text = f" (Match: {link_confidence:.0%})" if link_confidence else ""

            response_parts.append(
                f"{i}. **{name}**{funding_text}{confidence_text}\n   Provider: {provider}{deadline_text}"
            )

        if total > 5:
            response_parts.append(f"\n...and {total - 5} more scholarships.")

        # Add contextual follow-up suggestions
        if program_context.get("unresolved_context") and program_context["unresolved_context"].get("university_name"):
            response_parts.append(
                f"\n\nNote: **{program_context['unresolved_context']['university_name']}** "
                "wasn't found in our program database, so I showed scholarships based on your profile. "
                "Would you like to search for specific programs at this university first?"
            )
        else:
            response_parts.append(
                "\nWould you like more details about any of these scholarships, "
                "or should I refine the search with different criteria?"
            )

        return "\n".join(response_parts)

    async def _record_scholarship_discovery_call(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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
    ) -> None:
        """Log an SDA agent call for audit trail."""
        repo = self.agent_call_log_repo
        if repo is None:
            return
        try:
            await repo.create_log(
                log_id=str(uuid.uuid4()),
                workflow_run_id=workflow_run_id,
                user_id=user_id,
                chat_id=chat_id,
                target_service="scholarship-discovery",
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
                retry_of_log_id=None,
            )
        except (aiomysql.Error, RuntimeError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("sda_call_log_write_failed", operation=operation, error=str(exc))

    @staticmethod
    def _truncate_scholarship_response_for_logging(result: Any, max_items: int = 5) -> Optional[dict[str, Any]]:
        """Truncate SDA response to bounded subset for agent_call_logs storage."""
        if not isinstance(result, dict):
            return None

        truncated: dict[str, Any] = {}

        if "total" in result:
            truncated["total"] = result["total"]

        if "page" in result:
            truncated["page"] = result["page"]

        data = result.get("data")
        if isinstance(data, list):
            truncated["data_count"] = len(data)
            truncated["scholarship_ids"] = [
                item.get("id") for item in data[:max_items] if isinstance(item, dict) and item.get("id")
            ]

        return truncated if truncated else None

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        """Convert perf_counter start time to elapsed milliseconds."""
        return max(0, int((time.perf_counter() - started_at) * 1000))

    @staticmethod
    def _truncate_response_for_logging(
        result: Any, max_answer_len: int = 500, max_items: int = 5
    ) -> Optional[dict[str, Any]]:
        """Truncate PDA response to bounded subset for agent_call_logs storage.

        Extracts key metadata (answer length, counts) without storing full arrays
        that could bloat the database or exceed column limits.
        """
        if not isinstance(result, dict):
            return None

        truncated: dict[str, Any] = {}

        answer = result.get("answer") or result.get("response")
        if isinstance(answer, str):
            truncated["answer_length"] = len(answer)
            truncated["answer_preview"] = answer[:max_answer_len] + ("..." if len(answer) > max_answer_len else "")

        for key in ("programs", "institutions", "sources", "results"):
            if isinstance(result.get(key), list):
                items = result[key]
                truncated[f"{key}_count"] = len(items)
                if items and isinstance(items[0], dict):
                    truncated[f"{key}_ids"] = [item.get("id") for item in items[:max_items] if item.get("id")]

        for key in ("status", "intent", "query", "session_id", "model"):
            if key in result:
                truncated[key] = result[key]

        if isinstance(result.get("data"), dict):
            data = result["data"]
            if isinstance(data.get("answer"), str):
                truncated["data_answer_length"] = len(data["answer"])

        return truncated if truncated else None

    async def _create_workflow_run(
        self,
        *,
        workflow_run_id: str,
        user_id: str,
        chat_id: Optional[str],
        workflow_type: str,
        workflow_state: str,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        repo = self.workflow_run_repo
        if repo is None:
            return
        try:
            await repo.create_run(
                run_id=workflow_run_id,
                user_id=user_id,
                chat_id=chat_id,
                workflow_type=workflow_type,
                workflow_state=workflow_state,
                context=context,
            )
        except (aiomysql.Error, RuntimeError, ValueError, TypeError) as exc:  # pragma: no cover
            logger.warning("workflow_run_create_failed", workflow_run_id=workflow_run_id, error=str(exc))

    async def _complete_workflow_run(
        self,
        *,
        workflow_run_id: str,
        workflow_status: str,
        workflow_state: Optional[str] = None,
        error_message: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        repo = self.workflow_run_repo
        if repo is None:
            return
        try:
            await repo.complete_run(
                run_id=workflow_run_id,
                status=workflow_status,
                workflow_state=workflow_state,
                error_message=error_message,
                context=context,
            )
        except (aiomysql.Error, RuntimeError, ValueError, TypeError) as exc:  # pragma: no cover
            logger.warning("workflow_run_complete_failed", workflow_run_id=workflow_run_id, error=str(exc))

    async def _get_latest_failed_agent_call_log(self, *, user_id: str, chat_id: str) -> Optional[dict[str, Any]]:
        repo = self.agent_call_log_repo
        if repo is None:
            return None
        try:
            return await repo.get_latest_failed_log(
                user_id=user_id,
                chat_id=chat_id,
                target_service="student-profile",
            )
        except (aiomysql.Error, RuntimeError, ValueError, TypeError) as exc:  # pragma: no cover
            logger.warning("agent_call_log_lookup_failed", user_id=user_id, chat_id=chat_id, error=str(exc))
            return None

    async def _has_recent_profile_gate_reminder(self, chat_id: str) -> bool:
        """Check if user was already reminded about incomplete profile in this chat.

        Returns True if there's a recent assistant message with profile gate denial,
        indicating the user has already been told about missing profile fields.
        """
        try:
            recent = await self.message_repo.list_by_chat(chat_id=chat_id, limit=10, order="desc")
        except (aiomysql.Error, RuntimeError, ValueError, TypeError) as exc:
            logger.warning("profile_gate_reminder_lookup_failed", chat_id=chat_id, error=str(exc))
            return False

        if not isinstance(recent, list):
            return False

        for message in recent:
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "").lower() != "assistant":
                continue

            metadata = message.get("metadata")
            if not isinstance(metadata, dict):
                continue

            profile_gate = metadata.get("profile_gate")
            if not isinstance(profile_gate, dict):
                continue

            if profile_gate.get("allowed") is False:
                reason = str(profile_gate.get("reason") or "")
                if "profile_incomplete" in reason:
                    return True

        return False

    async def _resolve_assistant_content(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        *,
        gate: dict[str, Any],
        collected_from_chat: Optional[dict[str, Any]],
        clarification_question: Optional[str],
        detected_intent: str,
        target_agent: Optional[str],
        user_id: str,
        chat_id: str,
        content: str,
        workflow_run_id: str,
        is_eligibility_clarification_reply: bool = False,
        pending_eligibility_context: Optional[dict[str, Any]] = None,
        pending_application_support_context: Optional[dict[str, Any]] = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Generate assistant content based on profile gate status and intent.

        If gate is allowed, generate appropriate response for the intent.
        If gate is denied but user was already reminded, allow bypass for domain queries.
        Otherwise, return profile completion guidance.

        Returns:
            (response_dict, updated_gate) where response_dict contains:
            - answer: str - the assistant's response text
            - agent_reasoning: Optional[dict] - reasoning from downstream agents (PDA, SDA, etc.)
            - source: str - which agent/service generated the response
        """
        if gate["allowed"]:
            response = await self._generate_intent_response(
                detected_intent=detected_intent,
                target_agent=target_agent,
                user_id=user_id,
                chat_id=chat_id,
                content=content,
                workflow_run_id=workflow_run_id,
                gate=gate,
                is_eligibility_clarification_reply=is_eligibility_clarification_reply,
                pending_eligibility_context=pending_eligibility_context,
                pending_application_support_context=pending_application_support_context,
            )
            return response, gate

        applied_fields = _as_string_list((collected_from_chat or {}).get("applied_fields"))
        no_fields_extracted = not applied_fields
        is_domain_query = detected_intent not in {"profile_completion", "out_of_scope"}
        was_already_reminded = await self._has_recent_profile_gate_reminder(chat_id)
        missing_fields = _as_string_list(gate.get("missing_required_fields") or gate.get("missing_fields") or [])

        if no_fields_extracted and is_domain_query and was_already_reminded and detected_intent != "eligibility_check":
            logger.info(
                "profile_gate_bypass_after_reminder",
                user_id=user_id,
                chat_id=chat_id,
                detected_intent=detected_intent,
                target_agent=target_agent,
            )
            updated_gate = {**gate, "allowed": True, "reason": "bypass_after_reminder"}
            response = await self._generate_intent_response(
                detected_intent=detected_intent,
                target_agent=target_agent,
                user_id=user_id,
                chat_id=chat_id,
                content=content,
                workflow_run_id=workflow_run_id,
                gate=updated_gate,
                is_eligibility_clarification_reply=is_eligibility_clarification_reply,
                pending_eligibility_context=pending_eligibility_context,
            )
            return response, updated_gate

        if is_domain_query and self._is_explicit_intent_request(content, detected_intent):
            response_text = self._build_intent_gated_response(
                detected_intent=detected_intent,
                missing_fields=missing_fields,
                clarification_question=None,
            )
            return {"answer": response_text, "agent_reasoning": None, "source": "orchestrator"}, gate

        response_text = self._build_profile_gate_response(
            missing_fields,
            applied_fields=applied_fields,
            pending_clarification_fields=_as_string_list(
                (collected_from_chat or {}).get("pending_clarification_fields")
            ),
            clarification_question=clarification_question,
        )
        return {"answer": response_text, "agent_reasoning": None, "source": "orchestrator"}, gate

    async def _generate_intent_response(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        *,
        detected_intent: str,
        target_agent: Optional[str],
        user_id: str,
        chat_id: str,
        content: str,
        workflow_run_id: str,
        gate: dict[str, Any],
        is_eligibility_clarification_reply: bool = False,
        pending_eligibility_context: Optional[dict[str, Any]] = None,
        pending_application_support_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Generate response for allowed intent - either agent call or static response.

        Returns:
            Dict with 'answer' (str) and optional 'agent_reasoning' (dict).
        """
        if detected_intent == "program_discovery":
            pda_result = await self._handle_program_discovery(
                user_id=user_id,
                chat_id=chat_id,
                content=content,
                workflow_run_id=workflow_run_id,
                gate=gate,
            )
            await self._persist_chat_dashboard_snapshot(
                user_id=user_id,
                chat_id=chat_id,
                detected_intent=detected_intent,
                content=content,
                programs=pda_result.get("dashboard_items"),
            )
            pda_result["refresh_tabs"] = ["programs", "scholarships"]
            return pda_result

        if detected_intent == "scholarship_search":
            sda_result = await self._handle_scholarship_search(
                user_id=user_id,
                chat_id=chat_id,
                content=content,
                workflow_run_id=workflow_run_id,
                gate=gate,
            )
            await self._persist_chat_dashboard_snapshot(
                user_id=user_id,
                chat_id=chat_id,
                detected_intent=detected_intent,
                content=content,
                scholarships=sda_result.get("dashboard_items"),
            )
            sda_result["refresh_tabs"] = ["programs", "scholarships"]
            return sda_result

        if detected_intent == "eligibility_check":
            return await self._handle_eligibility_check(
                user_id=user_id,
                chat_id=chat_id,
                content=content,
                workflow_run_id=workflow_run_id,
                gate=gate,
                is_clarification_reply=is_eligibility_clarification_reply,
                pending_eligibility_context=pending_eligibility_context,
            )

        if target_agent == "application-support":
            response = await self._build_application_support_response(
                user_id=user_id,
                chat_id=chat_id,
                user_message=content,
                detected_intent=detected_intent,
                pending_application_support_context=pending_application_support_context,
            )
            return {
                "answer": response["answer"],
                "agent_reasoning": response.get("agent_reasoning"),
                "source": "application_support",
                "refresh_tabs": response.get("refresh_tabs") or [],
                "focus_application_id": response.get("focus_application_id"),
            }
        return {
            "answer": self._build_intent_ready_response(detected_intent, content, gate),
            "agent_reasoning": None,
            "source": "orchestrator",
        }

    async def _get_latest_assistant_message(self, chat_id: str) -> Optional[dict[str, Any]]:
        """Fetch the latest assistant turn for clarification-aware intent handling."""
        try:
            recent = await self.message_repo.list_by_chat(chat_id=chat_id, limit=5, order="desc")
        except (aiomysql.Error, RuntimeError, ValueError, TypeError) as exc:  # pragma: no cover
            logger.warning("latest_assistant_message_lookup_failed", chat_id=chat_id, error=str(exc))
            return None

        if not isinstance(recent, list):
            return None

        return next(
            (
                message
                for message in recent
                if isinstance(message, dict) and str(message.get("role") or "").lower() == "assistant"
            ),
            None,
        )

    @staticmethod
    def _maybe_override_intent_for_clarification_reply(
        detected_intent: str,
        content: str,
        latest_assistant_message: Optional[dict[str, Any]],
    ) -> str:
        """Keep short clarification replies in the correct intent flow.

        Handles two cases:
        1. Profile-gate blocking: ambiguous short replies (e.g. "yes", "Computer Science")
           should continue the profile_completion path.
        2. Eligibility clarification pending: after the assistant asks for a program/scholarship
           name or ID, the user's reply should continue as eligibility_check even when it
           contains no explicit eligibility keywords (e.g. "NUS Master of Computing").
        """
        if not isinstance(latest_assistant_message, dict):
            return detected_intent

        metadata = latest_assistant_message.get("metadata")
        if not isinstance(metadata, dict):
            return detected_intent

        pending_intent = str(metadata.get("pending_intent") or "").strip()
        if pending_intent and pending_intent != detected_intent:
            if pending_intent == "eligibility_check":
                return "eligibility_check"
            # For short slot answers that classifier marks as profile_completion,
            # continue the previously blocked domain intent.
            if detected_intent == "profile_completion" and not ChatService._is_explicit_intent_request(
                content, detected_intent
            ):
                return pending_intent

        profile_gate = metadata.get("profile_gate")
        if not isinstance(profile_gate, dict):
            return detected_intent

        reason = str(profile_gate.get("reason") or "")
        if reason in {"intent_out_of_scope", "intent_agent_unavailable"}:
            return detected_intent

        # While profile completion is still blocking, prefer profile intent for
        # short/non-explicit follow-up answers (for example, slot answers like
        # "Computer Science") so they don't get routed to domain agents.
        if profile_gate.get("allowed") is False and not ChatService._is_explicit_intent_request(
            content, detected_intent
        ):
            return "profile_completion"

        return detected_intent

    # -- Private Helpers --

    async def _get_chat_or_404(self, chat_id: str, user_id: str) -> dict[str, Any]:
        """Get chat and validate ownership."""
        chat = await self.chat_repo.get_by_id_with_user(chat_id)

        if not chat:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")

        if chat.get("deleted_at") is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")

        if chat.get("user_id") != user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")

        return chat

    def _generate_placeholder_response(self, _user_message: str) -> str:
        """Generate a placeholder assistant response."""
        return (
            "Thanks for your message! I'm Ouroboros, your AI assistant for discovering "
            "scholarships and programs. I'm currently being set up to help you with:\n\n"
            "• Finding scholarships that match your profile\n"
            "• Discovering graduate programs worldwide\n"
            "• Checking your eligibility for opportunities\n"
            "• Helping with your applications\n\n"
            "Full functionality is coming soon. Stay tuned!"
        )

    def _build_profile_gate_response(
        self,
        missing_fields: list[str],
        applied_fields: Optional[list[str]] = None,
        pending_clarification_fields: Optional[list[str]] = None,
        clarification_question: Optional[str] = None,
    ) -> str:
        """Return a deterministic guidance message when profile completion is required."""
        if not missing_fields:
            return (
                "I need to finish your profile before I can continue with scholarship and program help. "
                "Please update your profile and try again."
            )

        if clarification_question:
            applied = [self._format_profile_field_label(field) for field in (applied_fields or []) if field]
            if applied:
                applied_text = self._join_humanized_labels(applied)
                return f"Great, I saved your {applied_text}. {clarification_question}"
            # No fields saved yet - fall through to the friendly first-time format below

        first_missing = self._format_profile_field_label(missing_fields[0])
        applied = [self._format_profile_field_label(field) for field in (applied_fields or []) if field]
        pending = [self._format_profile_field_label(field) for field in (pending_clarification_fields or []) if field]
        if applied:
            applied_text = self._join_humanized_labels(applied)
            if pending:
                pending_text = self._join_humanized_labels(pending)
                return (
                    f"Great, I saved your {applied_text}. "
                    f"I need to confirm your {pending_text} before I continue. "
                    f"Next, please share your {first_missing}."
                )
            return f"Great, I saved your {applied_text}. " f"Next, please share your {first_missing}."
        if pending:
            pending_text = self._join_humanized_labels(pending)
            return (
                "I can help with scholarships and program searches, but I need to finish your profile first. "
                f"I need to confirm your {pending_text}. "
                f"Let's start with your {first_missing}."
            )
        return (
            "I can help with scholarships and program searches, but I need to finish your profile first. "
            f"Let's start with your {first_missing}. Once you send that, I'll ask for the next detail."
        )

    @staticmethod
    def _build_orchestrator_thoughts(*, detected_intent: str) -> dict[str, Any]:
        normalized_intent = str(detected_intent or "unknown")
        confidence = 0.9 if normalized_intent != "profile_completion" else 0.8
        return {
            "intent": normalized_intent,
            "intent_confidence": confidence,
        }

    @staticmethod
    def _build_gate_decision(gate: dict[str, Any]) -> dict[str, Any]:
        missing_fields = _as_string_list(gate.get("missing_required_fields") or gate.get("missing_fields") or [])
        allowed = bool(gate.get("allowed"))
        reason = str(gate.get("reason") or "")
        if reason == "bypass_after_reminder":
            gate_status = "BYPASSED"
        elif allowed:
            gate_status = "COMPLETE"
        elif reason == "intent_agent_unavailable":
            gate_status = "UNAVAILABLE"
        elif reason == "intent_out_of_scope":
            gate_status = "OUT_OF_SCOPE"
        else:
            gate_status = "INCOMPLETE"
        human_reason = {
            "profile_complete_for_intent": "Profile is complete for this intent.",
            "profile_incomplete_for_intent": "Profile is missing required fields for this intent.",
            "intent_out_of_scope": "This request is outside supported scope.",
            "intent_agent_unavailable": "The required agent is currently unavailable.",
            "bypass_after_reminder": "Request allowed after prior profile reminder.",
        }.get(reason, reason or "Gate decision computed.")
        return {
            "allowed": allowed,
            "status": gate_status,
            "missing_fields": missing_fields,
            "reason": human_reason,
        }

    @staticmethod
    def _resolve_selected_agent(*, gate: dict[str, Any], target_agent: Optional[str], detected_intent: str) -> str:
        reason = str(gate.get("reason") or "")
        if reason == "intent_out_of_scope":
            return "orchestrator"
        if reason == "intent_agent_unavailable":
            return str(target_agent or "orchestrator")
        if gate.get("allowed") is False:
            return "student-profile"
        if target_agent:
            return str(target_agent)
        if detected_intent == "profile_completion":
            return "student-profile"
        return "orchestrator"

    @staticmethod
    def _build_routing_decision(
        *,
        selected_agent: str,
        target_agent: Optional[str],
        gate: dict[str, Any],
        detected_intent: str,
    ) -> dict[str, Any]:
        reason = str(gate.get("reason") or "")
        if reason == "intent_out_of_scope":
            routing_reason = "Request is out of scope, handled by orchestrator boundary response."
            confidence = 0.95
        elif reason == "intent_agent_unavailable":
            routing_reason = f"Intent maps to '{target_agent}', but agent is unavailable."
            confidence = 0.92
        elif gate.get("allowed") is False:
            routing_reason = "Profile is incomplete, so routing to student-profile flow."
            confidence = 0.94
        else:
            routing_reason = f"Profile gate passed for intent '{detected_intent}'."
            confidence = 0.9

        return {
            "selected_agent": selected_agent,
            "routing_reason": routing_reason,
            "confidence": confidence,
            "alternative_agents": [],
        }

    @staticmethod
    def _build_agent_reasoning(
        *,
        gate: dict[str, Any],
        collected_from_chat: Optional[dict[str, Any]],
        agent_reasoning_from_response: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        # Priority 1: Agent reasoning from downstream response (PDA, SDA, etc.)
        if isinstance(agent_reasoning_from_response, dict):
            return dict(agent_reasoning_from_response)

        # Priority 2: Agent reasoning from SPA via collected_from_chat
        from_student_profile = isinstance(collected_from_chat, dict) and isinstance(
            collected_from_chat.get("agent_reasoning"), dict
        )
        if from_student_profile:
            return dict(collected_from_chat["agent_reasoning"])

        # Priority 3: Explicit non-profile gate blocks
        reason = str(gate.get("reason") or "")
        if reason == "intent_agent_unavailable":
            target_agent = str(gate.get("target_agent") or "the required service")
            return {
                "approach": "Pause domain routing until the mapped agent is available.",
                "decision_factors": [
                    f"Mapped agent '{target_agent}' is currently unavailable.",
                    "Profile data was not the blocker for this turn.",
                ],
                "next_field": None,
                "confidence": 0.92,
            }
        if reason == "intent_out_of_scope":
            return {
                "approach": "Apply orchestrator scope boundary handling.",
                "decision_factors": ["Request is outside supported education-planning scope."],
                "next_field": None,
                "confidence": 0.95,
            }

        # Priority 4: Profile gate denial reasoning
        if gate.get("allowed") is False:
            missing_fields = _as_string_list(gate.get("missing_required_fields") or gate.get("missing_fields") or [])
            next_field = missing_fields[0] if missing_fields else None
            factors: list[str] = ["Profile gate is not yet complete."]
            if missing_fields:
                factors.append(f"Missing fields: {', '.join(missing_fields)}")
            return {
                "approach": "Collect required profile fields before domain agent routing.",
                "decision_factors": factors,
                "next_field": next_field,
                "confidence": 0.9,
            }

        return None

    def _build_intent_gated_response(
        self,
        *,
        detected_intent: str,
        missing_fields: list[str],
        clarification_question: Optional[str] = None,
    ) -> str:
        if clarification_question:
            return clarification_question

        if not missing_fields:
            return (
                "I need to finish your profile before I can continue with this request. "
                "Please update your profile and try again."
            )

        intent_labels = {
            "program_discovery": "discover programs",
            "scholarship_search": "search scholarships",
            "eligibility_check": "check eligibility",
            "application_planning": "plan applications",
            "apply_to_named_school": "plan your application",
        }
        action_label = intent_labels.get(detected_intent, "help with this request")
        first_missing = self._format_profile_field_label(missing_fields[0])
        return (
            f"I can help {action_label}, but I need to finish your profile first. "
            f"Please share your {first_missing}."
        )

    @staticmethod
    def _is_explicit_intent_request(content: str, detected_intent: str) -> bool:
        lowered = (content or "").strip().lower()
        if not lowered:
            return False

        if detected_intent == "program_discovery":
            return any(token in lowered for token in ["discover", "find", "search", "explore"]) and any(
                token in lowered for token in ["program", "degree", "university", "school", "course", "major"]
            )

        if detected_intent == "scholarship_search":
            return any(token in lowered for token in ["scholarship", "funding", "grant", "financial aid"])

        if detected_intent == "eligibility_check":
            return any(token in lowered for token in ["eligible", "eligibility", "qualify", "qualified"])

        if detected_intent in {"application_planning", "apply_to_named_school"}:
            return any(token in lowered for token in APPLICATION_SUPPORT_KEYWORDS | {"application", "apply"})

        return False

    @staticmethod
    def _extract_clarification_question(clarifications: Optional[dict[str, Any]]) -> Optional[str]:
        if not isinstance(clarifications, dict):
            return None

        queue = clarifications.get("clarification_queue")
        if not isinstance(queue, list) or not queue:
            return None

        first_item = queue[0]
        if not isinstance(first_item, dict):
            return None

        question = first_item.get("question")
        if isinstance(question, str) and question.strip():
            return question.strip()
        return None

    @staticmethod
    def _extract_clarification_field(clarifications: Optional[dict[str, Any]]) -> Optional[str]:
        if not isinstance(clarifications, dict):
            return None

        queue = clarifications.get("clarification_queue")
        if not isinstance(queue, list) or not queue:
            return None

        first_item = queue[0]
        if not isinstance(first_item, dict):
            return None

        field = first_item.get("field")
        if isinstance(field, str) and field.strip():
            return field.strip()
        return None

    @staticmethod
    def _is_profile_gate_followup_prompt(latest_assistant_message: Optional[dict[str, Any]]) -> bool:
        if not isinstance(latest_assistant_message, dict):
            return False

        metadata = latest_assistant_message.get("metadata")
        if not isinstance(metadata, dict):
            return False

        profile_gate = metadata.get("profile_gate")
        if not isinstance(profile_gate, dict):
            return False

        if profile_gate.get("allowed") is not False:
            return False

        reason = str(profile_gate.get("reason") or "")
        return reason not in {"intent_out_of_scope", "intent_agent_unavailable"}

    @classmethod
    def _augment_metadata_with_active_profile_slot(
        cls,
        metadata: Optional[dict[str, Any]],
        content: str,
    ) -> dict[str, Any]:
        enriched = dict(metadata or {})
        if isinstance(enriched.get("active_profile_slot"), dict):
            return enriched

        inferred_slot = cls._infer_active_profile_slot_from_content(content)
        if inferred_slot is not None:
            enriched["active_profile_slot"] = inferred_slot
        return enriched

    @classmethod
    def _build_active_profile_slot(
        cls,
        *,
        clarification_field: Optional[str],
        missing_fields: list[str],
        clarification_question: Optional[str],
        assistant_content: str,
    ) -> Optional[dict[str, Any]]:
        if clarification_question and clarification_field:
            return {
                "field": clarification_field,
                "label": cls._format_profile_field_label(clarification_field),
                "expected_type": cls._profile_field_expected_type(clarification_field),
                "source": "clarification_queue",
            }

        inferred = cls._infer_active_profile_slot_from_content(assistant_content)
        if inferred is not None:
            return inferred

        if missing_fields:
            field = str(missing_fields[0] or "").strip()
            if field:
                return {
                    "field": field,
                    "label": cls._format_profile_field_label(field),
                    "expected_type": cls._profile_field_expected_type(field),
                    "source": "profile_gate_missing_field",
                }
        return None

    @classmethod
    def _extract_active_profile_slot(
        cls,
        latest_assistant_message: Optional[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        if not isinstance(latest_assistant_message, dict):
            return None

        metadata = latest_assistant_message.get("metadata")
        if isinstance(metadata, dict):
            existing_slot = metadata.get("active_profile_slot")
            if isinstance(existing_slot, dict):
                field = str(existing_slot.get("field") or "").strip()
                if field:
                    return {
                        "field": field,
                        "label": str(existing_slot.get("label") or cls._format_profile_field_label(field)),
                        "expected_type": str(
                            existing_slot.get("expected_type") or cls._profile_field_expected_type(field)
                        ),
                        "source": str(existing_slot.get("source") or "profile_gate_missing_field"),
                    }

        return cls._infer_active_profile_slot_from_content(str(latest_assistant_message.get("content") or ""))

    @classmethod
    def _infer_active_profile_slot_from_content(cls, content: str) -> Optional[dict[str, Any]]:
        text = (content or "").strip()
        if not text:
            return None

        prompt_patterns = (
            r"(?:Let's start with your|Next, please share your)\s+{label}\b",
            r"What is your\s+{label}\?",
            r"Please share your\s+{label}\b",
        )
        candidate_fields = [
            "current_degree_level",
            "target_degree_level",
            "gpa",
            "gpa_scale",
            "intended_field_of_study",
            "target_study_country",
            "enrollment_timeline",
            "funding_source",
            "email",
            "full_name",
        ]
        for field in candidate_fields:
            label = re.escape(cls._format_profile_field_label(field))
            for template in prompt_patterns:
                if re.search(template.format(label=label), text, flags=re.IGNORECASE):
                    return {
                        "field": field,
                        "label": cls._format_profile_field_label(field),
                        "expected_type": cls._profile_field_expected_type(field),
                        "source": "message_inference",
                    }
        return None

    @classmethod
    def _extract_slot_bound_profile_updates(
        cls,
        content: str,
        active_profile_slot: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(active_profile_slot, dict):
            return {}

        field = str(active_profile_slot.get("field") or "").strip()
        if not field:
            return {}

        if field in {"current_degree_level", "target_degree_level"}:
            normalized_degree = cls._normalize_degree_level_reply(content)
            if normalized_degree:
                return {field: normalized_degree}

        extracted = ProfileGateService.extract_profile_fields_from_chat(content, [field])
        if not isinstance(extracted, dict) or field not in extracted:
            return {}
        return {key: value for key, value in extracted.items() if value is not None}

    @staticmethod
    def _normalize_degree_level_reply(content: str) -> Optional[str]:
        lowered = (content or "").strip().lower()
        if not lowered:
            return None

        if re.search(r"\b(phd|doctorate|doctoral)\b", lowered):
            return "phd"
        if re.search(r"\b(master|masters|master's|mba|m\.?sc|ms)\b", lowered):
            return "master"
        if re.search(r"\b(bachelor|bachelors|bachelor's|b\.?sc|bs|ba|undergraduate)\b", lowered):
            return "bachelor"
        if re.search(r"\b(high school|highschool)\b", lowered):
            return "high_school"
        return None

    @staticmethod
    def _profile_field_expected_type(field: str) -> str:
        if field in {"current_degree_level", "target_degree_level"}:
            return "degree_level"
        if field in {"gpa", "gpa_scale", "gpa_highest"}:
            return "numeric"
        if field == "target_study_country":
            return "country"
        if field == "enrollment_timeline":
            return "timeline"
        if field == "funding_source":
            return "funding_source"
        return "text"

    @staticmethod
    def _format_profile_field_label(field: str) -> str:
        labels = {
            "full_name": "full name",
            "email": "email address",
            "current_degree_level": "current degree level",
            "target_degree_level": "target degree level",
            "gpa": "GPA",
            "gpa_highest": "GPA",
            "gpa_scale": "GPA scale",
            "intended_field_of_study": "intended field of study",
            "target_study_country": "preferred study country",
            "enrollment_timeline": "enrollment timeline",
            "funding_source": "funding source",
            "gender": "gender",
            "about_me": "about me",
            "profession": "profession",
            "interest": "interest",
        }
        return labels.get(field, field.replace("_", " "))

    @staticmethod
    def _join_humanized_labels(labels: list[str]) -> str:
        clean = [label for label in labels if label]
        if not clean:
            return ""
        if len(clean) == 1:
            return clean[0]
        if len(clean) == 2:
            return f"{clean[0]} and {clean[1]}"
        return f"{', '.join(clean[:-1])}, and {clean[-1]}"

    def _build_out_of_scope_response(self, intent_policy: dict[str, Any]) -> str:
        fallback = intent_policy.get("fallback") if isinstance(intent_policy, dict) else None
        suggestions = fallback.get("suggest_intents") if isinstance(fallback, dict) else None
        if not isinstance(suggestions, list):
            suggestions = []

        suggestion_text = ", ".join(str(item).replace("_", " ") for item in suggestions if isinstance(item, str))
        if not suggestion_text:
            suggestion_text = "scholarship search, program discovery, or application planning"

        return "I can only help with education planning tasks right now. " f"You can ask me about {suggestion_text}."

    def _build_agent_unavailable_response(self, detected_intent: str, target_agent: str) -> str:
        """Return a clear in-scope message when the mapped downstream service is unavailable."""
        intent_label_map = {
            "program_discovery": "program discovery",
            "scholarship_search": "scholarship search",
            "eligibility_check": "eligibility checks",
            "application_planning": "application planning",
            "apply_to_named_school": "application planning",
        }
        intent_label = intent_label_map.get(detected_intent, "this request")
        return (
            f"I understood this as {intent_label}, but that service is temporarily unavailable right now "
            f"({target_agent}). Please try again shortly."
        )

    @staticmethod
    def _detect_application_support_action(user_message: str) -> str:
        return detect_application_support_action(user_message)

    @staticmethod
    def _extract_target_program_from_message(user_message: str) -> Optional[str]:
        clean_message = re.sub(r"\s+", " ", (user_message or "").strip())
        if not clean_message:
            return None

        patterns = [
            r"\b(?:for|at|to)\s+(.+)$",
            r"\b(?:university|school|program)\s*[:=-]\s*(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, clean_message, flags=re.IGNORECASE)
            if match:
                candidate = re.sub(r"[?.!]+$", "", match.group(1).strip())
                if candidate:
                    return candidate[:180]
        return None

    @staticmethod
    def _application_support_unavailable_response() -> str:
        return (
            "I understood this as an application-support task, but the application-support service "
            "is temporarily unavailable right now. Please try again shortly."
        )

    def _format_application_support_response(self, action: str, payload: Any) -> str:
        if not isinstance(payload, dict):
            return "Application support completed the request, but returned an unexpected response."

        data = payload.get("data")
        message = str(payload.get("message") or "Application support completed the request.")

        if action in {"sop", "cover_letter"} and isinstance(data, dict):
            content = str(data.get("content") or "").strip()
            if content:
                return content

        if action == "checklist":
            checklist = data if isinstance(data, dict) else None
            if checklist is None and isinstance(data, list) and data:
                checklist = data[0] if isinstance(data[0], dict) else None
            if isinstance(checklist, dict):
                items = checklist.get("items") or []
                if isinstance(items, list) and items:
                    lines = []
                    for item in items[:6]:
                        if isinstance(item, dict) and item.get("description"):
                            lines.append(f"- {item['description']}")
                    if lines:
                        return "Here is the current application checklist:\n" + "\n".join(lines)
            return message

        if action == "deadlines" and isinstance(data, list):
            if not data:
                return "I checked your application deadlines and did not find any saved deadlines yet."
            lines = []
            for item in data[:6]:
                if not isinstance(item, dict):
                    continue
                date_text = item.get("deadline_date") or "date pending"
                description = item.get("item_description") or "Application deadline"
                lines.append(f"- {date_text}: {description}")
            if lines:
                return "Here are the application deadlines I found:\n" + "\n".join(lines)

        return message

    async def _build_application_support_response(
        self,
        *,
        user_id: str,
        chat_id: str,
        user_message: str,
        detected_intent: str,
        trace_id: Optional[str] = None,
        pending_application_support_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Track the target application first, then run the requested support action."""
        effective_message = user_message
        action = self._detect_application_support_action(user_message)
        target_label = self._extract_target_program_from_message(user_message)
        entity_type = self._detect_application_target_entity_type(user_message)

        if isinstance(pending_application_support_context, dict) and not self._is_explicit_intent_request(
            user_message, detected_intent
        ):
            effective_message = str(pending_application_support_context.get("source_message") or user_message)
            action = str(pending_application_support_context.get("action") or action)
            target_label = str(pending_application_support_context.get("target_program") or target_label or "")
            entity_type = (
                str(pending_application_support_context.get("target_entity_type") or entity_type or "program").strip()
                or "program"
            )

        if action in {"sop", "cover_letter", "checklist", "deadlines"} and not target_label:
            return {
                "answer": (
                    "I can help with that application task, but I need the target program or scholarship first. "
                    "Please send the exact name you want me to work on."
                ),
                "agent_reasoning": None,
            }

        try:
            target = await self._resolve_application_tracking_target(
                user_id=user_id,
                user_message=effective_message,
                detected_intent=detected_intent,
                requested_entity_type=entity_type,
                target_label=target_label,
            )
            if target is None:
                return {
                    "answer": (
                        "I can help with that application task, but I couldn't resolve which program or scholarship "
                        "you meant. Please send the exact name first."
                    ),
                    "agent_reasoning": None,
                }

            application = await self.application_tracking_service.start_application(
                user_id=user_id,
                body=TrackedApplicationCreate(**target),
            )

            response_text: Optional[str] = None
            agent_reasoning: Optional[dict[str, Any]] = None

            if action == "sop":
                if application.get("entity_type") != "program":
                    response_text = (
                        "I started tracking this scholarship in Applications, but SOP drafting is only "
                        "available for program applications right now."
                    )
                else:
                    result = await self.application_tracking_service.generate_sop(
                        user_id=user_id,
                        application_id=application["id"],
                    )
                    output = result.get("output") if isinstance(result, dict) else None
                    agent_reasoning = (
                        output.get("data", {}).get("agent_reasoning")
                        if isinstance(output, dict) and isinstance(output.get("data"), dict)
                        else None
                    )
                    response_text = self._format_application_support_response("sop", output)
            elif action == "cover_letter":
                result = await self.application_tracking_service.generate_cover_letter(
                    user_id=user_id,
                    application_id=application["id"],
                )
                output = result.get("output") if isinstance(result, dict) else None
                agent_reasoning = (
                    output.get("data", {}).get("agent_reasoning")
                    if isinstance(output, dict) and isinstance(output.get("data"), dict)
                    else None
                )
                response_text = self._format_application_support_response("cover_letter", output)
            elif action == "deadlines":
                result = await self.application_tracking_service.sync_deadline(
                    user_id=user_id,
                    application_id=application["id"],
                )
                output = result.get("output") if isinstance(result, dict) else None
                response_text = self._format_application_support_response("deadlines", output)
            else:
                checklist_output = application.get("checklist_output")
                if isinstance(checklist_output, dict):
                    response_text = self._format_application_support_response("checklist", checklist_output)
                else:
                    result = await self.application_tracking_service.create_checklist(
                        user_id=user_id,
                        application_id=application["id"],
                    )
                    output = result.get("output") if isinstance(result, dict) else None
                    response_text = self._format_application_support_response("checklist", output)

            return {
                "answer": response_text or "I updated your Applications tab with the latest application task.",
                "agent_reasoning": agent_reasoning,
                "refresh_tabs": ["applications"],
                "focus_application_id": application.get("id"),
            }
        except (AgentClientError, HTTPException) as exc:
            status_code = exc.status_code if isinstance(exc, AgentClientError) else exc.status_code
            logger.warning(
                "application_support_request_failed",
                user_id=user_id,
                chat_id=chat_id,
                trace_id=trace_id,
                action=action,
                status_code=status_code,
                error=str(exc),
            )
            return {
                "answer": self._application_support_unavailable_response(),
                "agent_reasoning": None,
            }
        except (RuntimeError, ValueError, TypeError) as exc:
            logger.warning(
                "application_support_request_unavailable",
                user_id=user_id,
                chat_id=chat_id,
                trace_id=trace_id,
                action=action,
                error=str(exc),
            )
            return {
                "answer": self._application_support_unavailable_response(),
                "agent_reasoning": None,
            }

    async def _resolve_application_tracking_target(
        self,
        *,
        user_id: str,
        user_message: str,
        detected_intent: str,
        requested_entity_type: str,
        target_label: str,
    ) -> Optional[dict[str, Any]]:
        clean_label = self._normalize_application_target_label(target_label or user_message)
        if not clean_label:
            return None

        dashboard_target = await self._find_application_target_in_dashboard(
            user_id=user_id,
            requested_entity_type=requested_entity_type,
            query=clean_label,
        )
        if dashboard_target is not None:
            return dashboard_target

        entity_type = "scholarship" if requested_entity_type == "scholarship" else "program"
        synthetic_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{user_id}:{entity_type}:{self._normalize_match_text(clean_label)}",
            )
        )
        title_key = "name" if entity_type == "scholarship" else "program_name"
        return {
            "entity_type": entity_type,
            "entity_id": synthetic_id,
            "title": clean_label,
            "provider": None,
            "match_score": None,
            "deadline": None,
            "source_data": {
                title_key: clean_label,
                "source_message": user_message,
                "intent": detected_intent,
            },
        }

    async def _find_application_target_in_dashboard(
        self,
        *,
        user_id: str,
        requested_entity_type: str,
        query: str,
    ) -> Optional[dict[str, Any]]:
        dashboard_payload = await self.result_aggregation_service.get_dashboard(
            user_id=user_id,
            include_history=False,
        )
        dashboard = dashboard_payload.get("dashboard") if isinstance(dashboard_payload, dict) else None
        if not isinstance(dashboard, dict):
            return None

        section_names = (
            ["scholarships", "programs"] if requested_entity_type == "scholarship" else ["programs", "scholarships"]
        )
        best_match: Optional[dict[str, Any]] = None
        best_score = 0
        for section_name in section_names:
            section = dashboard.get(section_name)
            if not isinstance(section, dict) or not isinstance(section.get("items"), list):
                continue
            for item in section["items"]:
                if not isinstance(item, dict):
                    continue
                score = self._score_application_dashboard_item(query=query, item=item)
                if score <= best_score:
                    continue
                entity_type = "scholarship" if section_name == "scholarships" else "program"
                title = self._application_target_title(item, entity_type)
                if not title:
                    continue
                best_score = score
                best_match = {
                    "entity_type": entity_type,
                    "entity_id": str(item.get("id") or ""),
                    "title": title,
                    "provider": self._application_target_provider(item, entity_type),
                    "match_score": self._application_target_match_score(item),
                    "deadline": self._application_target_deadline(item),
                    "source_data": dict(item),
                }

        if best_match and best_match.get("entity_id"):
            return best_match
        return None

    def _score_application_dashboard_item(self, *, query: str, item: dict[str, Any]) -> int:
        normalized_query = self._normalize_match_text(query)
        if not normalized_query:
            return 0
        candidates = [
            self._application_target_title(item, "program"),
            self._application_target_title(item, "scholarship"),
            self._application_target_provider(item, "program"),
            self._application_target_provider(item, "scholarship"),
        ]
        best_score = 0
        for candidate in candidates:
            normalized_candidate = self._normalize_match_text(candidate or "")
            if not normalized_candidate:
                continue
            if normalized_candidate == normalized_query:
                return 100
            if normalized_query in normalized_candidate:
                best_score = max(best_score, 80)
            elif normalized_candidate in normalized_query:
                best_score = max(best_score, 70)
            elif all(token in normalized_candidate for token in normalized_query.split()):
                best_score = max(best_score, 60)
        return best_score

    @staticmethod
    def _application_target_title(item: dict[str, Any], entity_type: str) -> Optional[str]:
        if entity_type == "scholarship":
            return ChatService._first_text(item.get("name"), item.get("title"), "")
        return ChatService._first_text(item.get("program_name"), item.get("name"), item.get("title"), "")

    @staticmethod
    def _application_target_provider(item: dict[str, Any], entity_type: str) -> Optional[str]:
        if entity_type == "scholarship":
            return ChatService._first_text(item.get("provider"), item.get("organization"), "")
        return ChatService._first_text(item.get("institution_name"), item.get("university"), item.get("provider"), "")

    @staticmethod
    def _application_target_match_score(item: dict[str, Any]) -> Optional[float]:
        match = item.get("match")
        if not isinstance(match, dict):
            return None
        try:
            return float(match.get("match_score"))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _application_target_deadline(item: dict[str, Any]) -> Optional[str]:
        deadline = item.get("deadline")
        if isinstance(deadline, str) and deadline.strip():
            return deadline.strip()
        return None

    @staticmethod
    def _detect_application_target_entity_type(user_message: str) -> str:
        lowered = (user_message or "").lower()
        if any(token in lowered for token in ("scholarship", "grant", "bursary", "fellowship", "award")):
            return "scholarship"
        return "program"

    @classmethod
    def _normalize_application_target_label(cls, value: str) -> str:
        cleaned = re.sub(r"\s+", " ", (value or "").strip())
        if not cleaned:
            return ""
        prefixes = [
            "program ",
            "the program ",
            "scholarship ",
            "the scholarship ",
            "application for ",
            "apply to ",
        ]
        lowered = cleaned.lower()
        for prefix in prefixes:
            if lowered.startswith(prefix):
                return cleaned[len(prefix) :].strip()
        return cleaned

    @staticmethod
    def _normalize_match_text(value: str) -> str:
        lowered = (value or "").strip().lower()
        return re.sub(r"[^a-z0-9]+", " ", lowered).strip()

    def _build_intent_ready_response(
        self,
        detected_intent: str,
        user_message: str,
        gate: dict[str, Any],
    ) -> str:
        """Return intent-aware guidance once profile gate is satisfied."""
        lowered = (user_message or "").lower()
        if detected_intent == "profile_completion":
            if any(
                token in lowered
                for token in ["cv", "resume", "upload", "document", "analysis", "feedback", "processing"]
            ):
                return (
                    "I can help process your CV for analysis and profile feedback. "
                    "Please upload it through the `/api/v1/workflows/profile-upload` "
                    "endpoint, and I will extract your details from it."
                )

            missing_optional = list(gate.get("missing_optional_fields") or [])
            if missing_optional:
                labels = [self._format_profile_field_label(field) for field in missing_optional]
                optional_text = self._join_humanized_labels(labels)
                return (
                    "Your core profile is complete. "
                    f"I still do not have your {optional_text}. "
                    "If you want, you can share those now or we can move on to programs and scholarships."
                )

            return (
                "Your profile is complete for the current readiness requirements. "
                "If you want, I can now help you discover programs, search scholarships, or plan applications."
            )

        if detected_intent == "program_discovery":
            return (
                "I can help discover programs that fit your profile. "
                "Tell me what field, country, or university you're interested in."
            )

        if detected_intent == "scholarship_search":
            return (
                "Great, I can help find scholarships suitable for your profile. "
                "Tell me your target study country and degree goal, and I will refine the scholarship matches."
            )

        if detected_intent == "eligibility_check":
            return (
                "Great, I can help check your eligibility. "
                "Share the name or ID of the program or scholarship you want to evaluate, "
                "and I will run the check against your profile."
            )

        if detected_intent in {"application_planning", "apply_to_named_school"}:
            return (
                "Great, I can help plan your application steps. "
                "Share the university and intake timeline, and I will outline what to prepare next."
            )

        return self._generate_placeholder_response(user_message)

    def _build_pending_application_support_context(self, user_message: str, detected_intent: str) -> dict[str, Any]:
        """Persist the original application-support request across profile-gate turns."""
        return {
            "intent": detected_intent,
            "action": self._detect_application_support_action(user_message),
            "target_program": self._extract_target_program_from_message(user_message),
            "target_entity_type": self._detect_application_target_entity_type(user_message),
            "source_message": user_message,
        }

    def _generate_title_from_message(self, content: str) -> str:
        """Generate a chat title from the first message content."""
        clean = content.strip()
        if len(clean) <= MAX_AUTO_TITLE_LENGTH:
            return clean

        truncated = clean[:MAX_AUTO_TITLE_LENGTH]
        last_space = truncated.rfind(" ")
        if last_space > MAX_AUTO_TITLE_LENGTH // 2:
            truncated = truncated[:last_space]

        return truncated + "..."
