"""Tests for workflow visibility endpoints."""

# pylint: disable=protected-access

from fastapi import Depends, HTTPException
from fastapi.testclient import TestClient

from app.api import workflows as workflows_api
from app.main import app
from app.middleware.auth_middleware import get_current_user_id
from app.services.profile_gate_service import ProfileGateService

client = TestClient(app)


def _return_user_1() -> str:
    return "user-1"


def _stub_chat_repo():
    class _StubChatRepo:
        async def get_by_id_with_user(self, chat_id: str):
            assert chat_id == "chat-1"
            return {
                "id": chat_id,
                "user_id": "user-1",
                "status": "active",
                "deleted_at": None,
            }

    return _StubChatRepo()


def _stub_message_repo():
    class _StubMessageRepo:
        async def list_by_chat(self, **_kwargs):
            assert _kwargs["chat_id"] == "chat-1"
            assert _kwargs["limit"] == 1
            assert _kwargs["order"] == "desc"
            return [
                {
                    "id": "msg-1",
                    "role": "assistant",
                    "metadata": {
                        "profile_gate": {
                            "allowed": False,
                        }
                    },
                }
            ]

    return _StubMessageRepo()


def _stub_student_profile_client():
    class _StubStudentProfileClient:
        async def parse_document_upload(self, **_kwargs):
            assert _kwargs["user_id"] == "user-1"
            assert _kwargs["file_name"] == "cv.pdf"
            assert _kwargs["file_content_base64"]
            assert _kwargs["intent"] == "profile_completion"
            assert _kwargs["document_type"] == "cv"
            assert _kwargs["target_degree_hint"] == "master"
            assert _kwargs["run_gap_analysis"] is True
            return {
                "profile_id": "profile-1",
                "llm_model": "gpt-test",
                "gap_analysis": {"readiness_score": 0.5},
            }

    return _StubStudentProfileClient()


def _stub_chat_service():
    class _StubChatService:
        async def retry_last_agent_call(self, user_id: str, chat_id: str):
            assert user_id == "user-1"
            assert chat_id == "chat-1"
            return {
                "chat_id": chat_id,
                "retried": True,
                "source_message_id": "msg-user-1",
                "assistant_message": {"id": "msg-assistant-1"},
                "profile_gate": {"allowed": True},
                "chat": {"id": chat_id},
            }

    return _StubChatService()


def _stub_chat_service_raises():
    class _StubChatService:
        async def retry_last_agent_call(self, user_id: str, chat_id: str):
            assert user_id == "user-1"
            assert chat_id == "chat-1"
            raise HTTPException(status_code=400, detail="No user message available to retry")

    return _StubChatService()


def test_get_chat_workflow_status_returns_states():
    class _StubChatRepo:
        async def get_by_id_with_user(self, chat_id: str):
            assert chat_id == "chat-1"
            return {
                "id": chat_id,
                "user_id": "user-1",
                "status": "active",
                "deleted_at": None,
            }

    class _StubMessageRepo:
        async def list_by_chat(self, *, chat_id: str, limit: int, order: str):
            assert chat_id == "chat-1"
            assert limit == 1
            assert order == "desc"
            return [
                {
                    "id": "msg-1",
                    "role": "assistant",
                    "metadata": {
                        "profile_gate": {
                            "allowed": False,
                        }
                    },
                }
            ]

    class _StubProfileGateService:
        async def get_user_readiness(self, user_id: str, intent: str | None = None):
            assert user_id == "user-1"
            assert intent == "program_discovery"
            return {
                "user_id": user_id,
                "completed": False,
                "missing_fields": ["email"],
                "updated_at": "2026-04-12T00:00:00",
                "intent": intent,
            }

    def _stub_chat_repo_factory():
        return _StubChatRepo()

    def _stub_message_repo_factory():
        return _StubMessageRepo()

    def _stub_profile_gate_service_factory():
        return _StubProfileGateService()

    app.dependency_overrides[get_current_user_id] = _return_user_1
    app.dependency_overrides[workflows_api._get_chat_repo] = _stub_chat_repo_factory
    app.dependency_overrides[workflows_api._get_message_repo] = _stub_message_repo_factory
    app.dependency_overrides[workflows_api._get_profile_gate_service] = _stub_profile_gate_service_factory

    response = client.get("/api/v1/workflows/chats/chat-1/status", params={"intent": "program_discovery"})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["chat_workflow_state"] == "OPEN"
    assert payload["profile_readiness_workflow_state"] == "IN_PROGRESS"
    assert payload["agent_execution_state"] == "PROFILE_GATE"
    assert payload["latest_message_id"] == "msg-1"
    assert payload["profile_readiness"]["intent"] == "program_discovery"


def test_get_chat_workflow_status_returns_executing_for_latest_user_message():
    class _StubChatRepo:
        async def get_by_id_with_user(self, chat_id: str):
            assert chat_id == "chat-1"
            return {
                "id": chat_id,
                "user_id": "user-1",
                "status": "active",
                "deleted_at": None,
            }

    class _StubMessageRepo:
        async def list_by_chat(self, *, chat_id: str, limit: int, order: str):
            assert chat_id == "chat-1"
            assert limit == 1
            assert order == "desc"
            return [
                {
                    "id": "msg-1",
                    "role": "user",
                    "metadata": None,
                }
            ]

    class _StubProfileGateService:
        async def get_user_readiness(self, user_id: str, intent: str | None = None):
            assert user_id == "user-1"
            assert intent == "program_discovery"
            return {
                "user_id": user_id,
                "completed": True,
                "missing_fields": [],
                "updated_at": "2026-04-12T00:00:00",
                "intent": intent,
            }

    def _stub_chat_repo_factory():
        return _StubChatRepo()

    def _stub_message_repo_factory():
        return _StubMessageRepo()

    def _stub_profile_gate_service_factory():
        return _StubProfileGateService()

    app.dependency_overrides[get_current_user_id] = _return_user_1
    app.dependency_overrides[workflows_api._get_chat_repo] = _stub_chat_repo_factory
    app.dependency_overrides[workflows_api._get_message_repo] = _stub_message_repo_factory
    app.dependency_overrides[workflows_api._get_profile_gate_service] = _stub_profile_gate_service_factory

    response = client.get("/api/v1/workflows/chats/chat-1/status", params={"intent": "program_discovery"})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_execution_state"] == "EXECUTING"
    assert payload["latest_message_id"] == "msg-1"


def test_get_chat_workflow_status_returns_success_for_latest_assistant_message():
    class _StubChatRepo:
        async def get_by_id_with_user(self, chat_id: str):
            assert chat_id == "chat-1"
            return {
                "id": chat_id,
                "user_id": "user-1",
                "status": "active",
                "deleted_at": None,
            }

    class _StubMessageRepo:
        async def list_by_chat(self, *, chat_id: str, limit: int, order: str):
            assert chat_id == "chat-1"
            assert limit == 1
            assert order == "desc"
            return [
                {
                    "id": "msg-1",
                    "role": "assistant",
                    "metadata": {
                        "profile_gate": {
                            "allowed": True,
                        }
                    },
                }
            ]

    class _StubProfileGateService:
        async def get_user_readiness(self, user_id: str, intent: str | None = None):
            assert user_id == "user-1"
            assert intent == "program_discovery"
            return {
                "user_id": user_id,
                "completed": True,
                "missing_fields": [],
                "updated_at": "2026-04-12T00:00:00",
                "intent": intent,
            }

    def _stub_chat_repo_factory():
        return _StubChatRepo()

    def _stub_message_repo_factory():
        return _StubMessageRepo()

    def _stub_profile_gate_service_factory():
        return _StubProfileGateService()

    app.dependency_overrides[get_current_user_id] = _return_user_1
    app.dependency_overrides[workflows_api._get_chat_repo] = _stub_chat_repo_factory
    app.dependency_overrides[workflows_api._get_message_repo] = _stub_message_repo_factory
    app.dependency_overrides[workflows_api._get_profile_gate_service] = _stub_profile_gate_service_factory

    response = client.get("/api/v1/workflows/chats/chat-1/status", params={"intent": "program_discovery"})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_execution_state"] == "SUCCESS"
    assert payload["latest_message_id"] == "msg-1"


def test_get_profile_readiness_returns_intent():
    class _StubProfileGateService:
        async def get_user_readiness(self, user_id: str, intent: str | None = None):
            assert user_id == "user-1"
            assert intent == "scholarship_search"
            return {
                "user_id": user_id,
                "completed": True,
                "missing_fields": [],
                "optional_missing_fields": [],
                "updated_at": "2026-04-12T00:00:00",
                "intent": intent,
                "missing_required_fields": [],
                "missing_optional_fields": [],
            }

    def _stub_profile_gate_service_factory():
        return _StubProfileGateService()

    app.dependency_overrides[get_current_user_id] = _return_user_1
    app.dependency_overrides[workflows_api._get_profile_gate_service] = _stub_profile_gate_service_factory

    response = client.get("/api/v1/workflows/users/me/profile-readiness", params={"intent": "scholarship_search"})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "scholarship_search"
    assert payload["completed"] is True


def test_get_profile_readiness_defaults_intent_when_missing():
    class _StubProfileGateService:
        async def get_user_readiness(self, user_id: str, intent: str | None = None):
            assert user_id == "user-1"
            assert intent == "profile_completion"
            return {
                "user_id": user_id,
                "completed": True,
                "missing_fields": [],
                "optional_missing_fields": [],
                "updated_at": "2026-04-12T00:00:00",
                "intent": intent,
            }

    def _stub_profile_gate_service_factory():
        return _StubProfileGateService()

    app.dependency_overrides[get_current_user_id] = _return_user_1
    app.dependency_overrides[workflows_api._get_profile_gate_service] = _stub_profile_gate_service_factory

    response = client.get("/api/v1/workflows/users/me/profile-readiness")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "profile_completion"
    assert payload["completed"] is True


def test_get_chat_workflow_status_not_found():
    class _StubChatRepo:
        async def get_by_id_with_user(self, _chat_id: str):
            return None

    class _StubMessageRepo:
        async def list_by_chat(self, **_kwargs):
            return []

    class _StubProfileGateService:
        async def get_user_readiness(self, _user_id: str, _intent: str | None = None):
            return {"completed": False, "missing_fields": [], "updated_at": None}

    def _stub_chat_repo_factory():
        return _StubChatRepo()

    def _stub_message_repo_factory():
        return _StubMessageRepo()

    def _stub_profile_gate_service_factory():
        return _StubProfileGateService()

    app.dependency_overrides[get_current_user_id] = _return_user_1
    app.dependency_overrides[workflows_api._get_chat_repo] = _stub_chat_repo_factory
    app.dependency_overrides[workflows_api._get_message_repo] = _stub_message_repo_factory
    app.dependency_overrides[workflows_api._get_profile_gate_service] = _stub_profile_gate_service_factory

    response = client.get("/api/v1/workflows/chats/missing/status")

    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Chat not found"


def test_retry_last_agent_call():
    class _StubProfileGateService:
        async def get_user_readiness(self, _user_id: str, _intent: str | None = None):
            return {"completed": True}

    class _StubChatService:
        def __init__(self, profile_gate_service: ProfileGateService):
            self.profile_gate_service = profile_gate_service

        async def retry_last_agent_call(self, user_id: str, chat_id: str):
            assert user_id == "user-1"
            assert chat_id == "chat-1"
            return {
                "chat_id": chat_id,
                "retried": True,
                "source_message_id": "msg-user-1",
                "assistant_message": {"id": "msg-assistant-1"},
                "profile_gate": {"allowed": True},
                "chat": {"id": chat_id},
            }

    def _stub_profile_gate_service_factory():
        return _StubProfileGateService()

    def _stub_chat_service_factory(
        profile_gate_service: ProfileGateService = Depends(workflows_api._get_profile_gate_service),
    ):
        return _StubChatService(profile_gate_service)

    app.dependency_overrides[get_current_user_id] = _return_user_1
    app.dependency_overrides[workflows_api._get_profile_gate_service] = _stub_profile_gate_service_factory
    app.dependency_overrides[workflows_api._get_chat_service] = _stub_chat_service_factory

    response = client.post("/api/v1/workflows/chats/chat-1/retry-last-agent-call")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["chat_id"] == "chat-1"
    assert payload["retried"] is True
    assert payload["source_message_id"] == "msg-user-1"


def test_retry_last_agent_call_no_message():
    class _StubProfileGateService:
        async def get_user_readiness(self, _user_id: str, _intent: str | None = None):
            return {"completed": True}

    class _StubChatServiceRaises:
        def __init__(self, profile_gate_service: ProfileGateService):
            self.profile_gate_service = profile_gate_service

        async def retry_last_agent_call(self, user_id: str, chat_id: str):
            assert user_id == "user-1"
            assert chat_id == "chat-1"
            raise HTTPException(status_code=400, detail="No user message available to retry")

    def _stub_profile_gate_service_factory():
        return _StubProfileGateService()

    def _stub_chat_service_raises_factory(
        profile_gate_service: ProfileGateService = Depends(workflows_api._get_profile_gate_service),
    ):
        return _StubChatServiceRaises(profile_gate_service)

    app.dependency_overrides[get_current_user_id] = _return_user_1
    app.dependency_overrides[workflows_api._get_profile_gate_service] = _stub_profile_gate_service_factory
    app.dependency_overrides[workflows_api._get_chat_service] = _stub_chat_service_raises_factory

    response = client.post("/api/v1/workflows/chats/chat-1/retry-last-agent-call")

    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "No user message available to retry"


def test_profile_upload_forwards_to_student_profile():
    class _StubProfileGateService:
        def invalidate_readiness_cache(self, _user_id: str, _intent: str | None = None):
            pass

    def _stub_profile_gate_service_factory():
        return _StubProfileGateService()

    def _stub_student_profile_client_factory():
        return _stub_student_profile_client()

    app.dependency_overrides[get_current_user_id] = _return_user_1
    app.dependency_overrides[workflows_api._get_student_profile_client] = _stub_student_profile_client_factory
    app.dependency_overrides[workflows_api._get_profile_gate_service] = _stub_profile_gate_service_factory

    response = client.post(
        "/api/v1/workflows/profile-upload",
        headers={"Authorization": "Bearer test"},
        files={"file": ("cv.pdf", b"pdf-bytes", "application/pdf")},
        data={
            "intent": "profile_completion",
            "document_type": "cv",
            "target_degree_hint": "master",
            "run_gap_analysis": "true",
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile_id"] == "profile-1"
    assert payload["gap_analysis"]["readiness_score"] == 0.5


def test_profile_upload_invalidates_readiness_cache():
    invalidated: list[tuple[str, str | None]] = []

    class _StubStudentProfileClient:
        async def parse_document_upload(self, **_kwargs):
            assert _kwargs["user_id"] == "user-1"
            return {"profile_id": "profile-1"}

    class _StubProfileGateService:
        def invalidate_readiness_cache(self, user_id: str, intent: str | None = None):
            invalidated.append((user_id, intent))

    def _stub_student_profile_client_factory():
        return _StubStudentProfileClient()

    def _stub_profile_gate_service_factory():
        return _StubProfileGateService()

    app.dependency_overrides[get_current_user_id] = _return_user_1
    app.dependency_overrides[workflows_api._get_student_profile_client] = _stub_student_profile_client_factory
    app.dependency_overrides[workflows_api._get_profile_gate_service] = _stub_profile_gate_service_factory

    response = client.post(
        "/api/v1/workflows/profile-upload",
        headers={"Authorization": "Bearer test"},
        files={"file": ("cv.pdf", b"pdf-bytes", "application/pdf")},
        data={"intent": "profile_completion", "document_type": "cv"},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert invalidated == [("user-1", "profile_completion")]
