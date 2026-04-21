"""Workflow visibility endpoints for readiness, uploads, and orchestration state."""

import base64
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.clients.student_profile_client import StudentProfileClient
from app.core.database import get_pool
from app.core.logging import get_logger
from app.middleware.auth_middleware import get_current_user_id
from app.repositories.chat_repo import ChatRepository
from app.repositories.message_repo import MessageRepository
from app.services.chat_service import ChatService
from app.services.profile_gate_service import ProfileGateService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/workflows", tags=["Workflows"])


def _get_profile_gate_service() -> ProfileGateService:
    return ProfileGateService()


def _get_chat_repo() -> ChatRepository:
    return ChatRepository(get_pool())


def _get_message_repo() -> MessageRepository:
    return MessageRepository(get_pool())


def _get_chat_service(profile_gate_service: ProfileGateService = Depends(_get_profile_gate_service)) -> ChatService:
    return ChatService(profile_gate_service=profile_gate_service)


def _get_student_profile_client() -> StudentProfileClient:
    return StudentProfileClient()


@router.get("/users/me/profile-readiness")
async def get_my_profile_readiness(
    user_id: str = Depends(get_current_user_id),
    intent: str | None = Query(default=None),
    profile_gate_service: ProfileGateService = Depends(_get_profile_gate_service),
):
    """Return the current user's profile readiness snapshot."""
    normalized_intent = intent or "profile_completion"
    return await profile_gate_service.get_user_readiness(user_id, intent=normalized_intent)


@router.get("/chats/{chat_id}/status")
async def get_chat_workflow_status(
    chat_id: str,
    user_id: str = Depends(get_current_user_id),
    intent: str | None = Query(default=None),
    chat_repo: ChatRepository = Depends(_get_chat_repo),
    message_repo: MessageRepository = Depends(_get_message_repo),
    profile_gate_service: ProfileGateService = Depends(_get_profile_gate_service),
):
    """Return chat lifecycle state, profile readiness state, and latest execution state."""
    chat = await chat_repo.get_by_id_with_user(chat_id)
    if not chat or chat.get("user_id") != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")

    normalized_intent = intent or "profile_completion"
    readiness = await profile_gate_service.get_user_readiness(user_id, intent=normalized_intent)
    messages = await message_repo.list_by_chat(chat_id=chat_id, limit=1, order="desc")
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
async def retry_last_agent_call(
    chat_id: str,
    user_id: str = Depends(get_current_user_id),
    chat_service: ChatService = Depends(_get_chat_service),
):
    """Retry the latest chat request by replaying the newest user message."""
    return await chat_service.retry_last_agent_call(user_id=user_id, chat_id=chat_id)


@router.post("/profile-upload")
async def upload_profile_document(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    file: UploadFile = File(...),
    intent: str = Form(default="profile_completion"),
    document_type: str = Form(default="cv"),
    target_degree_hint: str | None = Form(default=None),
    run_gap_analysis: bool = Form(default=False),
    chat_id: str | None = Form(default=None),
    user_id: str = Depends(get_current_user_id),
    student_profile_client: StudentProfileClient = Depends(_get_student_profile_client),
    profile_gate_service: ProfileGateService = Depends(_get_profile_gate_service),
    chat_service: ChatService = Depends(_get_chat_service),
):
    """Forward a CV/transcript upload from orchestrator to student-profile processing.

    If chat_id is provided, posts an assistant notice with the parsing result to that chat.
    This makes the upload visible in the chat history and auto-titles the chat.
    """
    raw_bytes = await file.read()
    file_content_base64 = base64.b64encode(raw_bytes).decode("utf-8")
    filename = file.filename or "uploaded_file"

    try:
        result = await student_profile_client.parse_document_upload(
            user_id=user_id,
            file_name=filename,
            file_content_base64=file_content_base64,
            intent=intent,
            document_type=document_type,
            target_degree_hint=target_degree_hint,
            run_gap_analysis=run_gap_analysis,
        )
        profile_data = result.get("data") if isinstance(result.get("data"), dict) else None
        profile_id = profile_data.get("profile_id") if isinstance(profile_data, dict) else None
        if isinstance(profile_data, dict) and isinstance(profile_id, str) and profile_id:
            clarifications = await profile_gate_service.get_profile_clarifications(user_id, profile_id)
            if isinstance(clarifications, dict):
                profile_data["clarification_queue"] = clarifications.get("clarification_queue", profile_data.get("clarification_queue", []))
                profile_data["react_decision_trace"] = clarifications.get(
                    "react_decision_trace", profile_data.get("react_decision_trace", {})
                )
        profile_gate_service.invalidate_readiness_cache(user_id, intent)

        if chat_id:
            notice_content = _build_document_upload_notice(result, document_type, filename)
            notice_title = _build_document_upload_title(document_type, filename)
            await chat_service.post_assistant_notice(
                user_id=user_id,
                chat_id=chat_id,
                content=notice_content,
                metadata={
                    "notice_type": "document_upload",
                    "notice_title": notice_title,
                    "document_type": document_type,
                    "file_name": filename,
                    "intent": intent,
                    "upload_result": result if isinstance(result, dict) else None,
                },
            )

        return result

    except Exception as exc:
        logger.error(
            "document_upload_failed",
            user_id=user_id,
            document_type=document_type,
            file_name=filename,
            error=str(exc),
            exc_info=True,
        )
        if chat_id:
            error_notice = (
                f"I encountered an issue while processing your {document_type}. "
                "Please try uploading again, or try a different file format."
            )
            try:
                await chat_service.post_assistant_notice(
                    user_id=user_id,
                    chat_id=chat_id,
                    content=error_notice,
                    metadata={
                        "notice_type": "document_upload_error",
                        "document_type": document_type,
                        "file_name": filename,
                        "error_code": "document_processing_failed",
                    },
                )
            except Exception as notice_exc:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "failed_to_post_document_error_notice",
                    chat_id=chat_id,
                    original_error=type(exc).__name__,
                    notice_error=str(notice_exc),
                )
        raise


def _build_document_upload_notice(result: dict[str, Any] | None, document_type: str, filename: str) -> str:
    """Build a human-readable notice message for document upload result."""
    doc_label = "CV" if document_type == "cv" else document_type.replace("_", " ").title()

    if not isinstance(result, dict):
        return f"I've received your {doc_label} ({filename}) and it's being processed."

    data = result.get("data") if isinstance(result.get("data"), dict) else result
    extracted_fields = data.get("extracted_fields") or data.get("applied_fields") or []
    gap_analysis = data.get("gap_analysis")

    parts = [f"I've processed your {doc_label} ({filename})."]

    if extracted_fields and isinstance(extracted_fields, list):
        field_labels = [f.replace("_", " ") for f in extracted_fields[:5]]
        fields_text = ", ".join(field_labels)
        parts.append(f"I extracted the following information: {fields_text}.")
        if len(extracted_fields) > 5:
            parts.append(f"({len(extracted_fields) - 5} more fields updated)")

    if isinstance(gap_analysis, dict):
        gaps = gap_analysis.get("missing_for_intent") or gap_analysis.get("gaps") or []
        if gaps and isinstance(gaps, list):
            gap_labels = [g.replace("_", " ") for g in gaps[:3]]
            gaps_text = ", ".join(gap_labels)
            parts.append(f"To complete your profile, I still need: {gaps_text}.")

    if not extracted_fields and not gap_analysis:
        parts.append("Your profile has been updated with the extracted information.")

    return " ".join(parts)


def _build_document_upload_title(document_type: str, filename: str) -> str:
    """Build a short title for chat from document upload."""
    doc_label = "CV" if document_type == "cv" else document_type.replace("_", " ").title()
    short_name = filename[:20] + "..." if len(filename) > 20 else filename
    return f"{doc_label} Upload: {short_name}"


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
