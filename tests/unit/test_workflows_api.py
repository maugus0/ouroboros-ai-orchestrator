"""Tests for workflow visibility endpoints."""

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import workflows as workflows_api
from app.main import app
from app.middleware.auth_middleware import get_current_user_id

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
        async def list_by_chat(self, **kwargs):
            assert kwargs["chat_id"] == "chat-1"
            assert kwargs["limit"] == 1
            assert kwargs["order"] == "desc"
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
        async def parse_document_upload(self, **kwargs):
            assert kwargs["user_id"] == "user-1"
            assert kwargs["file_name"] == "cv.pdf"
            assert kwargs["file_content_base64"]
            assert kwargs["intent"] == "profile_completion"
            assert kwargs["document_type"] == "cv"
            assert kwargs["target_degree_hint"] == "master"
            assert kwargs["run_gap_analysis"] is True
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


def test_get_chat_workflow_status_returns_states(monkeypatch):
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

    async def fake_get_user_readiness(user_id: str, intent: str | None = None):
        assert user_id == "user-1"
        assert intent == "program_discovery"
        return {
            "user_id": user_id,
            "completed": False,
            "missing_fields": ["email"],
            "updated_at": "2026-04-12T00:00:00",
            "intent": intent,
        }

    app.dependency_overrides[get_current_user_id] = _return_user_1
    monkeypatch.setattr(workflows_api, "_get_chat_repo", _stub_chat_repo)
    monkeypatch.setattr(workflows_api, "_get_message_repo", _stub_message_repo)
    monkeypatch.setattr(workflows_api.profile_gate_service, "get_user_readiness", fake_get_user_readiness)

    response = client.get("/api/v1/workflows/chats/chat-1/status", params={"intent": "program_discovery"})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["chat_workflow_state"] == "OPEN"
    assert payload["profile_readiness_workflow_state"] == "IN_PROGRESS"
    assert payload["agent_execution_state"] == "PROFILE_GATE"
    assert payload["latest_message_id"] == "msg-1"
    assert payload["profile_readiness"]["intent"] == "program_discovery"


def test_get_profile_readiness_returns_intent(monkeypatch):
    async def fake_get_user_readiness(user_id: str, intent: str | None = None):
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

    app.dependency_overrides[get_current_user_id] = _return_user_1
    monkeypatch.setattr(workflows_api.profile_gate_service, "get_user_readiness", fake_get_user_readiness)

    response = client.get("/api/v1/workflows/users/me/profile-readiness", params={"intent": "scholarship_search"})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "scholarship_search"
    assert payload["completed"] is True


def test_get_chat_workflow_status_not_found(monkeypatch):
    class _StubChatRepo:
        async def get_by_id_with_user(self, _chat_id: str):
            return None

    def _stub_chat_repo_missing():
        return _StubChatRepo()

    app.dependency_overrides[get_current_user_id] = _return_user_1
    monkeypatch.setattr(workflows_api, "_get_chat_repo", _stub_chat_repo_missing)

    response = client.get("/api/v1/workflows/chats/missing/status")

    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Chat not found"


def test_retry_last_agent_call(monkeypatch):
    app.dependency_overrides[get_current_user_id] = _return_user_1
    monkeypatch.setattr(workflows_api, "_get_chat_service", _stub_chat_service)

    response = client.post("/api/v1/workflows/chats/chat-1/retry-last-agent-call")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["chat_id"] == "chat-1"
    assert payload["retried"] is True
    assert payload["source_message_id"] == "msg-user-1"


def test_retry_last_agent_call_no_message(monkeypatch):
    app.dependency_overrides[get_current_user_id] = _return_user_1
    monkeypatch.setattr(workflows_api, "_get_chat_service", _stub_chat_service_raises)

    response = client.post("/api/v1/workflows/chats/chat-1/retry-last-agent-call")

    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "No user message available to retry"


def test_profile_upload_forwards_to_student_profile(monkeypatch):
    app.dependency_overrides[get_current_user_id] = _return_user_1
    monkeypatch.setattr(workflows_api, "_get_student_profile_client", _stub_student_profile_client)

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


def test_profile_upload_invalidates_readiness_cache(monkeypatch):
    invalidated: list[tuple[str, str | None]] = []

    class _StubStudentProfileClient:
        async def parse_document_upload(self, **kwargs):
            assert kwargs["user_id"] == "user-1"
            return {"profile_id": "profile-1"}

    class _StubProfileGateService:
        def invalidate_readiness_cache(self, user_id: str, intent: str | None = None):
            invalidated.append((user_id, intent))

    def _stub_student_profile_client_local():
        return _StubStudentProfileClient()

    app.dependency_overrides[get_current_user_id] = _return_user_1
    monkeypatch.setattr(workflows_api, "_get_student_profile_client", _stub_student_profile_client_local)
    monkeypatch.setattr(workflows_api, "profile_gate_service", _StubProfileGateService())

    response = client.post(
        "/api/v1/workflows/profile-upload",
        headers={"Authorization": "Bearer test"},
        files={"file": ("cv.pdf", b"pdf-bytes", "application/pdf")},
        data={"intent": "profile_completion", "document_type": "cv"},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert invalidated == [("user-1", "profile_completion")]
