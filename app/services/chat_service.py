"""Chat session business logic — create, send messages, list, delete."""

import base64
import binascii
import json
import re
import time
import uuid
from datetime import datetime
from typing import Any, Optional

import aiomysql
from fastapi import HTTPException, status

from app.clients.agent_client import AgentClientError
from app.clients.program_discovery_client import ProgramDiscoveryClient
from app.core.database import get_pool
from app.core.logging import get_logger
from app.repositories.agent_call_log_repo import AgentCallLogRepository
from app.repositories.chat_repo import ChatRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.project_repo import ProjectRepository
from app.repositories.workflow_run_repo import WorkflowRunRepository
from app.services.agent_availability_service import AgentAvailabilityService
from app.services.intent_registry_service import IntentRegistryService
from app.services.profile_gate_service import ProfileGateService

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


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if value is None:
        return []
    return [str(value)]


class ChatService:
    """Orchestrates chat session operations."""

    _RESPONSE_CACHE_TTL_SECONDS = 90
    _RESPONSE_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    def __init__(
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
    ) -> None:
        self._chat_repo = chat_repo
        self._message_repo = message_repo
        self._project_repo = project_repo
        self._profile_gate_service = profile_gate_service
        self._workflow_run_repo = workflow_run_repo
        self._agent_call_log_repo = agent_call_log_repo
        self._intent_registry_service = intent_registry_service
        self._agent_availability_service = agent_availability_service
        self._program_discovery_client = program_discovery_client

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
        readiness_signature = {
            "allowed": bool(gate.get("allowed")),
            "reason": str(gate.get("reason") or ""),
            "missing_required_fields": sorted(str(field) for field in gate.get("missing_required_fields") or []),
            "missing_optional_fields": sorted(str(field) for field in gate.get("missing_optional_fields") or []),
            "updated_at": str(gate.get("updated_at") or ""),
            "target_agent": target_agent or "",
        }
        signature_text = json.dumps(readiness_signature, sort_keys=True, separators=(",", ":"))
        return chat_id, f"{detected_intent}:{normalized_content}:{signature_text}"

    @classmethod
    def _get_cached_response(cls, cache_key: tuple[str, str]) -> Optional[dict[str, Any]]:
        cached = cls._RESPONSE_CACHE.get(cache_key)
        if cached is None:
            return None

        expires_at, payload = cached
        if time.monotonic() >= expires_at:
            cls._RESPONSE_CACHE.pop(cache_key, None)
            return None

        return dict(payload)

    @classmethod
    def _set_cached_response(cls, cache_key: tuple[str, str], payload: dict[str, Any]) -> None:
        cls._RESPONSE_CACHE[cache_key] = (time.monotonic() + cls._RESPONSE_CACHE_TTL_SECONDS, dict(payload))

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

    async def send_message(
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
            latest_assistant_message = await self._get_latest_assistant_message(chat_id)
            detected_intent = self._maybe_override_intent_for_clarification_reply(
                detected_intent,
                latest_assistant_message,
            )
            intent_policy = self.intent_registry_service.get_policy(detected_intent)
            target_agent = intent_policy.get("agent") if isinstance(intent_policy, dict) else None

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
                else:
                    collected_from_chat: dict[str, Any] | None = None

                    if not gate["allowed"]:
                        missing_fields = _as_string_list(
                            gate.get("missing_required_fields") or gate.get("missing_fields") or []
                        )
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
                        gate = await self.profile_gate_service.evaluate_gate(
                            user_id,
                            intent=detected_intent,
                            chat_id=chat_id,
                            workflow_run_id=workflow_run_id,
                            retry_of_log_id=retry_of_log_id,
                        )

                    if gate["allowed"]:
                        if target_agent == "program-discovery":
                            await self._attempt_program_discovery_probe(user_id=user_id, chat_id=chat_id)
                        assistant_content = self._build_intent_ready_response(
                            detected_intent,
                            content,
                            gate,
                        )
                    else:
                        assistant_content = self._build_profile_gate_response(
                            _as_string_list(gate.get("missing_required_fields") or gate.get("missing_fields") or []),
                            applied_fields=_as_string_list((collected_from_chat or {}).get("applied_fields")),
                            pending_clarification_fields=_as_string_list(
                                (collected_from_chat or {}).get("pending_clarification_fields")
                            ),
                        )

                    self._set_cached_response(
                        cache_key,
                        {
                            "assistant_content": assistant_content,
                            "gate": gate,
                            "target_agent": target_agent,
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
            assistant_message = await self.message_repo.create(
                message_id=assistant_message_id,
                chat_id=chat_id,
                role="assistant",
                content=assistant_content,
                metadata={
                    "profile_gate": gate,
                    "workflow_run_id": workflow_run_id,
                    "retry_of_log_id": retry_of_log_id,
                    "intent": detected_intent,
                },
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

        assistant_message_id = str(uuid.uuid4())
        assistant_message = await self.message_repo.create(
            message_id=assistant_message_id,
            chat_id=chat_id,
            role="assistant",
            content=content,
            metadata=metadata,
        )

        await self.chat_repo.increment_message_count(chat_id, increment=1)

        # When upload flow starts a chat without a user message, derive a title
        # from the first assistant notice so the chat is not shown as untitled.
        if int(chat.get("message_count") or 0) == 0:
            preferred_title = None
            if isinstance(metadata, dict):
                candidate_title = metadata.get("notice_title")
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
        latest_assistant_message: Optional[dict[str, Any]],
    ) -> str:
        """Keep short clarification replies in profile-completion flow.

        When the latest assistant message came from profile gating (not out-of-scope
        or unavailable-agent), ambiguous short replies like "yes" should continue
        the profile_completion path instead of boundary routing.
        """
        if detected_intent != "out_of_scope" or not isinstance(latest_assistant_message, dict):
            return detected_intent

        metadata = latest_assistant_message.get("metadata")
        if not isinstance(metadata, dict):
            return detected_intent

        profile_gate = metadata.get("profile_gate")
        if not isinstance(profile_gate, dict):
            return detected_intent

        reason = str(profile_gate.get("reason") or "")
        if reason in {"intent_out_of_scope", "intent_agent_unavailable"}:
            return detected_intent

        if profile_gate.get("allowed") is False:
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
    ) -> str:
        """Return a deterministic guidance message when profile completion is required."""
        if not missing_fields:
            return (
                "I need to finish your profile before I can continue with scholarship and program help. "
                "Please update your profile and try again."
            )

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
            if "singapore" in lowered:
                return (
                    "Great, I can help discover graduate programs in Singapore that fit your profile. "
                    "Share your preferred field or university (for example NUS or NTU), and I will narrow the options."
                )
            return (
                "Great, I can help discover programs that fit your profile. "
                "Tell me your target country or preferred universities, and I will narrow the best matches."
            )

        if detected_intent == "scholarship_search":
            return (
                "Great, I can help find scholarships suitable for your profile. "
                "Tell me your target study country and degree goal, and I will refine the scholarship matches."
            )

        if detected_intent == "eligibility_check":
            return (
                "Great, I can help check your eligibility. "
                "Share the program or scholarship criteria you want to evaluate, "
                "and I will walk through them with your profile."
            )

        if detected_intent in {"application_planning", "apply_to_named_school"}:
            return (
                "Great, I can help plan your application steps. "
                "Share the university and intake timeline, and I will outline what to prepare next."
            )

        return self._generate_placeholder_response(user_message)

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
