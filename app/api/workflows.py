"""Workflow visibility endpoints for readiness, uploads, and orchestration state."""

import base64
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.clients.student_profile_client import StudentProfileClient
from app.core.database import get_pool
from app.middleware.auth_middleware import get_current_user_id
from app.repositories.chat_repo import ChatRepository
from app.repositories.message_repo import MessageRepository
from app.services.chat_service import ChatService
from app.services.profile_gate_service import ProfileGateService

router = APIRouter(prefix="/api/v1/workflows", tags=["Workflows"])

profile_gate_service = ProfileGateService()


def _get_chat_repo() -> ChatRepository:
    return ChatRepository(get_pool())


def _get_message_repo() -> MessageRepository:
    return MessageRepository(get_pool())


def _get_chat_service() -> ChatService:
    return ChatService(profile_gate_service=profile_gate_service)


def _get_student_profile_client() -> StudentProfileClient:
    return StudentProfileClient()


@router.get("/users/me/profile-readiness")
async def get_my_profile_readiness(
    user_id: str = Depends(get_current_user_id),
    intent: str | None = Query(default=None),
):
    """Return the current user's profile readiness snapshot."""
    normalized_intent = intent or "profile_completion"
    return await profile_gate_service.get_user_readiness(user_id, intent=normalized_intent)


@router.get("/chats/{chat_id}/status")
async def get_chat_workflow_status(
    chat_id: str,
    user_id: str = Depends(get_current_user_id),
    intent: str | None = Query(default=None),
):
    """Return chat lifecycle state, profile readiness state, and latest execution state."""
    chat = await _get_chat_repo().get_by_id_with_user(chat_id)
    if not chat or chat.get("user_id") != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")

    normalized_intent = intent or "profile_completion"
    readiness = await profile_gate_service.get_user_readiness(user_id, intent=normalized_intent)
    messages = await _get_message_repo().list_by_chat(chat_id=chat_id, limit=1, order="desc")
    latest_message = messages[0] if messages else None

    return {
        "chat_id": chat_id,
        "chat_workflow_state": _map_chat_state(chat),
        "profile_readiness_workflow_state": _map_readiness_state(readiness),
        "agent_execution_state": _map_agent_execution_state(readiness, latest_message),
        "profile_readiness": readiness,
        "latest_message_id": latest_message.get("id") if isinstance(latest_message, dict) else None,
    }


@router.post("/chats/{chat_id}/retry-last-agent-call")
async def retry_last_agent_call(chat_id: str, user_id: str = Depends(get_current_user_id)):
    """Retry the latest chat request by replaying the newest user message."""
    return await _get_chat_service().retry_last_agent_call(user_id=user_id, chat_id=chat_id)


@router.post("/profile-upload")
async def upload_profile_document(
    file: UploadFile = File(...),
    intent: str = Form(default="profile_completion"),
    document_type: str = Form(default="cv"),
    target_degree_hint: str | None = Form(default=None),
    run_gap_analysis: bool = Form(default=False),
    user_id: str = Depends(get_current_user_id),
):
    """Forward a CV/transcript upload from orchestrator to student-profile processing."""
    raw_bytes = await file.read()
    file_content_base64 = base64.b64encode(raw_bytes).decode("utf-8")

    result = await _get_student_profile_client().parse_document_upload(
        user_id=user_id,
        file_name=file.filename or "uploaded_file",
        file_content_base64=file_content_base64,
        intent=intent,
        document_type=document_type,
        target_degree_hint=target_degree_hint,
        run_gap_analysis=run_gap_analysis,
    )
    profile_gate_service.invalidate_readiness_cache(user_id, intent)
    return result


def _map_chat_state(chat: dict[str, Any]) -> str:
    if chat.get("deleted_at") is not None:
        return "DELETED"
    if str(chat.get("status") or "").lower() == "archived":
        return "ARCHIVED"
    return "OPEN"


def _map_readiness_state(readiness: dict[str, Any]) -> str:
    if readiness.get("completed"):
        return "COMPLETE"
    missing_fields = list(readiness.get("missing_fields") or [])
    if readiness.get("updated_at") is None:
        return "UNKNOWN"
    if missing_fields:
        return "IN_PROGRESS"
    return "ERROR"


def _map_agent_execution_state(readiness: dict[str, Any], latest_message: dict[str, Any] | None) -> str:
    if not readiness.get("completed"):
        return "PROFILE_GATE"

    if not isinstance(latest_message, dict):
        return "RECEIVED"

    metadata = latest_message.get("metadata")
    latest_role = str(latest_message.get("role") or "").lower()

    if isinstance(metadata, dict):
        profile_gate = metadata.get("profile_gate")
        if isinstance(profile_gate, dict):
            if profile_gate.get("allowed") is False:
                return "PROFILE_GATE"
            if profile_gate.get("allowed") is True:
                return "SUCCESS"

    if latest_role == "assistant":
        return "SUCCESS"

    if latest_role == "user":
        return "EXECUTING"

    return "RECEIVED"
