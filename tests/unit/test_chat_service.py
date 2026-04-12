"""Unit tests for ChatService."""

# Pytest injects fixture names as test parameters (redefined-outer-name).
# Tests call private helpers on the service under test (protected-access).
# pylint: disable=redefined-outer-name,protected-access

import base64
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.chat_service import ChatService

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_chat_repo():
    """Create a mock ChatRepository."""
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.get_by_id_with_user = AsyncMock()
    repo.list_by_user = AsyncMock()
    repo.update_title = AsyncMock()
    repo.update_starred = AsyncMock()
    repo.update_project = AsyncMock()
    repo.get_project_id = AsyncMock()
    repo.soft_delete = AsyncMock()
    repo.increment_message_count = AsyncMock()
    repo.set_title_if_empty = AsyncMock()
    return repo


@pytest.fixture
def mock_message_repo():
    """Create a mock MessageRepository."""
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.list_by_chat = AsyncMock()
    repo.count_by_chat = AsyncMock()
    return repo


@pytest.fixture
def mock_project_repo():
    """Create a mock ProjectRepository."""
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.get_by_id_with_user = AsyncMock()
    repo.exists_for_user = AsyncMock()
    repo.increment_chat_count = AsyncMock()
    repo.soft_delete = AsyncMock()
    return repo


@pytest.fixture
def mock_profile_gate_service():
    """Create a mock profile gate service."""
    service = MagicMock()
    service.evaluate_gate = AsyncMock()
    service.collect_profile_updates_from_chat = AsyncMock()
    return service


@pytest.fixture
def mock_intent_registry_service():
    """Create a mock intent registry service."""
    service = MagicMock()
    service.detect_intent = MagicMock(return_value="program_discovery")
    service.get_policy = MagicMock(return_value={"agent": "program-discovery"})
    return service


@pytest.fixture
def mock_agent_availability_service():
    """Create a mock agent availability service."""
    service = MagicMock()
    service.is_agent_available = AsyncMock(return_value=True)
    return service


@pytest.fixture
def mock_program_discovery_client():
    """Create a mock program discovery client."""
    client = MagicMock()
    client.probe_health = AsyncMock(return_value={"status": "ok"})
    return client


@pytest.fixture
def chat_service(
    mock_chat_repo,
    mock_message_repo,
    mock_project_repo,
    mock_profile_gate_service,
    mock_intent_registry_service,
    mock_agent_availability_service,
    mock_program_discovery_client,
):
    """Create ChatService with mocked repositories."""
    ChatService._RESPONSE_CACHE.clear()
    return ChatService(
        chat_repo=mock_chat_repo,
        message_repo=mock_message_repo,
        project_repo=mock_project_repo,
        profile_gate_service=mock_profile_gate_service,
        intent_registry_service=mock_intent_registry_service,
        agent_availability_service=mock_agent_availability_service,
        program_discovery_client=mock_program_discovery_client,
    )


@pytest.fixture
def sample_chat():
    """Sample chat data."""
    return {
        "id": "chat-123",
        "user_id": "user-456",
        "title": "Test Chat",
        "status": "active",
        "is_starred": False,
        "project_id": None,
        "message_count": 0,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "deleted_at": None,
    }


@pytest.fixture
def sample_message():
    """Sample message data."""
    return {
        "id": "msg-789",
        "chat_id": "chat-123",
        "role": "user",
        "content": "Hello, world!",
        "metadata": None,
        "created_at": datetime.now(timezone.utc),
    }


# ── Create Chat Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_chat_empty(chat_service, mock_chat_repo, sample_chat, mock_profile_gate_service):
    """Test creating an empty chat without initial message."""
    mock_profile_gate_service.evaluate_gate.return_value = {
        "user_id": "user-456",
        "completed": True,
        "missing_fields": [],
        "updated_at": None,
        "allowed": True,
        "reason": "profile_complete",
    }
    mock_chat_repo.create.return_value = sample_chat

    result = await chat_service.create_chat(user_id="user-456", initial_message=None)

    assert result["id"] == "chat-123"
    assert result["user_id"] == "user-456"
    mock_chat_repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_create_chat_with_message(
    chat_service, mock_chat_repo, mock_message_repo, sample_chat, sample_message, mock_profile_gate_service
):
    """Test creating a chat with an initial message."""
    mock_profile_gate_service.evaluate_gate.return_value = {
        "user_id": "user-456",
        "completed": True,
        "missing_fields": [],
        "updated_at": None,
        "allowed": True,
        "reason": "profile_complete",
    }
    mock_chat_repo.create.return_value = sample_chat
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    await chat_service.create_chat(
        user_id="user-456",
        initial_message="Hello!",
    )

    assert mock_message_repo.create.call_count == 2
    assert mock_chat_repo.increment_message_count.called
    assert mock_chat_repo.set_title_if_empty.called


# ── Send Message Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_message_success(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    """Test sending a message successfully."""
    mock_profile_gate_service.evaluate_gate.return_value = {
        "user_id": "user-456",
        "completed": True,
        "missing_fields": [],
        "updated_at": None,
        "allowed": True,
        "reason": "profile_complete",
    }
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    result = await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="Hello!",
    )

    assert "user_message" in result
    assert "assistant_message" in result
    assert "chat" in result
    assert mock_message_repo.create.call_count == 2
    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert "Great, I can help" in assistant_kwargs["content"]


@pytest.mark.asyncio
async def test_send_message_reuses_cached_response_for_repeated_turns(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    """Repeated identical turns in the same chat should reuse the cached assistant response."""
    ChatService._RESPONSE_CACHE.clear()
    chat_service._build_intent_ready_response = MagicMock(return_value="cached-intent-response")
    mock_profile_gate_service.evaluate_gate.return_value = {
        "user_id": "user-456",
        "completed": True,
        "missing_fields": [],
        "optional_missing_fields": [],
        "updated_at": "2026-04-12T00:00:00",
        "allowed": True,
        "reason": "profile_complete_for_intent",
        "intent": "program_discovery",
        "missing_required_fields": [],
        "missing_optional_fields": [],
    }
    chat_service.intent_registry_service.detect_intent.return_value = "program_discovery"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "program-discovery"}
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="Find graduate programs for me",
    )
    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="Find graduate programs for me",
    )

    assert chat_service._build_intent_ready_response.call_count == 1
    assistant_messages = [
        call for call in mock_message_repo.create.call_args_list if call.kwargs.get("role") == "assistant"
    ]
    assert len(assistant_messages) == 2
    assert assistant_messages[-1].kwargs["content"] == "cached-intent-response"


@pytest.mark.asyncio
async def test_send_message_profile_gate_denied(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    """Test that incomplete profiles receive deterministic guidance."""
    mock_profile_gate_service.evaluate_gate.return_value = {
        "user_id": "user-456",
        "completed": False,
        "missing_fields": ["email", "profession"],
        "updated_at": None,
        "allowed": False,
        "reason": "profile_incomplete",
    }
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    result = await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="Hello!",
    )

    assert "assistant_message" in result
    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert "I can help with scholarships and program searches" in assistant_kwargs["content"]
    assert "Let's start with your email address." in assistant_kwargs["content"]
    assert assistant_kwargs["metadata"]["profile_gate"]["allowed"] is False


@pytest.mark.asyncio
async def test_post_assistant_notice_persists_assistant_message(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
):
    """Assistant notice should create assistant-only message and update chat counters."""
    assistant_notice = {
        "id": "msg-asst-001",
        "chat_id": "chat-123",
        "role": "assistant",
        "content": "Thanks for uploading your CV. What is your target degree level?",
        "metadata": {"source": "profile_upload_followup"},
        "created_at": datetime.now(timezone.utc),
    }
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 1}
    mock_message_repo.create.return_value = assistant_notice

    result = await chat_service.post_assistant_notice(
        user_id="user-456",
        chat_id="chat-123",
        content="Thanks for uploading your CV. What is your target degree level?",
        metadata={"source": "profile_upload_followup", "notice_title": "Profile Completion"},
    )

    assert result["assistant_message"]["role"] == "assistant"
    assert result["assistant_message"]["metadata"]["source"] == "profile_upload_followup"
    mock_message_repo.create.assert_called_once()
    _, kwargs = mock_message_repo.create.call_args
    assert kwargs["role"] == "assistant"
    assert kwargs["metadata"]["source"] == "profile_upload_followup"
    mock_chat_repo.increment_message_count.assert_called_once_with("chat-123", increment=1)
    mock_chat_repo.set_title_if_empty.assert_called_once()
    set_title_call_args = mock_chat_repo.set_title_if_empty.call_args.args
    assert set_title_call_args[0] == "chat-123"
    assert set_title_call_args[1] == "Profile Completion"


@pytest.mark.asyncio
async def test_send_message_profile_completion_returns_readiness_summary(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    """Profile completion should respond with a profile-specific readiness summary."""
    chat_service.intent_registry_service.detect_intent.return_value = "profile_completion"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "student-profile"}
    mock_profile_gate_service.evaluate_gate.return_value = {
        "user_id": "user-456",
        "completed": True,
        "missing_fields": [],
        "optional_missing_fields": ["target_study_country", "funding_source"],
        "updated_at": None,
        "allowed": True,
        "reason": "profile_complete_for_intent",
        "intent": "profile_completion",
        "missing_required_fields": [],
        "missing_optional_fields": ["target_study_country", "funding_source"],
    }

    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="let's complete my profile",
    )

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert "Your core profile is complete" in assistant_kwargs["content"]
    assert "preferred study country" in assistant_kwargs["content"]
    assert "funding source" in assistant_kwargs["content"]


@pytest.mark.asyncio
async def test_send_message_cv_upload_returns_upload_guidance(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    """CV upload requests should route to a CV upload guidance response."""
    chat_service.intent_registry_service.detect_intent.return_value = "profile_completion"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "student-profile"}
    mock_profile_gate_service.evaluate_gate.return_value = {
        "user_id": "user-456",
        "completed": True,
        "missing_fields": [],
        "optional_missing_fields": [],
        "updated_at": None,
        "allowed": True,
        "reason": "profile_complete_for_intent",
        "intent": "profile_completion",
        "missing_required_fields": [],
        "missing_optional_fields": [],
    }

    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="I'd like to upload my CV for processing, analysis and feedback on ORB",
    )

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert "process your CV" in assistant_kwargs["content"]
    assert "/api/v1/workflows/profile-upload" in assistant_kwargs["content"]


@pytest.mark.asyncio
async def test_send_message_profile_gate_uses_natural_labels_for_remaining_fields(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    """Test that saved and missing profile fields are rendered with natural labels."""
    mock_profile_gate_service.evaluate_gate.side_effect = [
        {
            "user_id": "user-456",
            "completed": False,
            "missing_fields": ["intended_field_of_study"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete",
        },
        {
            "user_id": "user-456",
            "completed": False,
            "missing_fields": ["intended_field_of_study"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete",
        },
    ]
    mock_profile_gate_service.collect_profile_updates_from_chat.return_value = {
        "applied_fields": ["gpa_highest", "gpa_scale"]
    }
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="4.00/5.00",
    )

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert "Great, I saved your GPA and GPA scale." in assistant_kwargs["content"]
    assert "Next, please share your intended field of study." in assistant_kwargs["content"]


@pytest.mark.asyncio
async def test_send_message_profile_gate_collects_and_rechecks(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    """Test that profile fields from chat are collected before the second gate decision."""
    mock_profile_gate_service.evaluate_gate.side_effect = [
        {
            "user_id": "user-456",
            "completed": False,
            "missing_fields": ["email"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete",
        },
        {
            "user_id": "user-456",
            "completed": True,
            "missing_fields": [],
            "updated_at": None,
            "allowed": True,
            "reason": "profile_complete",
        },
    ]
    mock_profile_gate_service.collect_profile_updates_from_chat.return_value = {"applied_fields": ["email"]}
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    result = await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="My email is jane@example.com",
    )

    assert "assistant_message" in result
    assert mock_profile_gate_service.evaluate_gate.await_count == 2
    mock_profile_gate_service.collect_profile_updates_from_chat.assert_awaited_once()
    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert "Great, I can help" in assistant_kwargs["content"]
    assert assistant_kwargs["metadata"]["profile_gate"]["allowed"] is True


@pytest.mark.asyncio
async def test_send_message_program_discovery_mentions_singapore_when_present(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
    mock_program_discovery_client,
):
    """Program discovery reply should acknowledge Singapore when user mentions it."""
    mock_profile_gate_service.evaluate_gate.return_value = {
        "user_id": "user-456",
        "completed": True,
        "missing_fields": [],
        "updated_at": None,
        "allowed": True,
        "reason": "profile_complete_for_intent",
    }
    chat_service.intent_registry_service.detect_intent.return_value = "program_discovery"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "program-discovery"}

    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="Discover graduate program in singapore",
    )

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert "programs in Singapore" in assistant_kwargs["content"]
    mock_program_discovery_client.probe_health.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_program_discovery_unavailable_still_probes(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
    mock_program_discovery_client,
):
    """Program-discovery should receive a best-effort probe even when unavailable."""
    chat_service.intent_registry_service.detect_intent.return_value = "program_discovery"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "program-discovery"}
    chat_service.agent_availability_service.is_agent_available.return_value = False

    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="Find programs for data science",
    )

    mock_profile_gate_service.evaluate_gate.assert_not_awaited()
    mock_program_discovery_client.probe_health.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_profile_gate_acknowledges_applied_fields(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    """When chat extraction applies fields but gate remains closed, assistant should acknowledge and ask next."""
    mock_profile_gate_service.evaluate_gate.side_effect = [
        {
            "user_id": "user-456",
            "completed": False,
            "missing_fields": ["email", "gpa"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete",
        },
        {
            "user_id": "user-456",
            "completed": False,
            "missing_fields": ["gpa"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete",
        },
    ]
    mock_profile_gate_service.collect_profile_updates_from_chat.return_value = {"applied_fields": ["email"]}
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="My email is jane@example.com",
    )

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert "Great, I saved your email address." in assistant_kwargs["content"]
    assert "Next, please share your GPA." in assistant_kwargs["content"]


@pytest.mark.asyncio
async def test_send_message_out_of_scope_returns_boundary_guidance(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    """Out-of-scope messages should return boundary guidance without profile gating."""
    chat_service.intent_registry_service.detect_intent.return_value = "out_of_scope"
    chat_service.intent_registry_service.get_policy.return_value = {
        "fallback": {
            "suggest_intents": ["scholarship_search", "program_discovery"],
        }
    }
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="Tell me a cooking recipe",
    )

    mock_profile_gate_service.evaluate_gate.assert_not_awaited()
    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert "I can only help with education planning tasks right now." in assistant_kwargs["content"]
    assert "scholarship search" in assistant_kwargs["content"]
    assert assistant_kwargs["metadata"]["intent"] == "out_of_scope"


@pytest.mark.asyncio
async def test_send_message_mapped_intent_with_unavailable_agent_returns_unavailable_message(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    """Mapped intents with unavailable agents should return unavailable-service guidance."""
    chat_service.intent_registry_service.detect_intent.return_value = "scholarship_search"
    chat_service.intent_registry_service.get_policy.return_value = {
        "agent": "scholarship-discovery",
        "fallback": {
            "suggest_intents": ["program_discovery", "application_planning"],
        },
    }
    chat_service.agent_availability_service.is_agent_available.return_value = False

    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="Find scholarship options for me",
    )

    mock_profile_gate_service.evaluate_gate.assert_not_awaited()
    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert "service is temporarily unavailable" in assistant_kwargs["content"]
    assert "scholarship-discovery" in assistant_kwargs["content"]
    assert assistant_kwargs["metadata"]["profile_gate"]["reason"] == "intent_agent_unavailable"


@pytest.mark.asyncio
async def test_send_message_out_of_scope_is_overridden_during_profile_clarification(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    """Short clarification replies should stay in profile-completion flow."""
    chat_service.intent_registry_service.detect_intent.return_value = "out_of_scope"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "student-profile"}

    mock_profile_gate_service.evaluate_gate.return_value = {
        "user_id": "user-456",
        "completed": False,
        "missing_fields": ["target_degree_level"],
        "updated_at": None,
        "allowed": False,
        "reason": "profile_incomplete_for_intent",
    }
    mock_profile_gate_service.collect_profile_updates_from_chat.return_value = {
        "applied_fields": ["target_degree_level"],
    }

    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message
    mock_message_repo.list_by_chat.return_value = [
        {
            "id": "assistant-prev-1",
            "role": "assistant",
            "content": "Let's start with your target degree level.",
            "metadata": {
                "profile_gate": {
                    "allowed": False,
                    "reason": "profile_incomplete_for_intent",
                }
            },
        }
    ]

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="yes",
    )

    evaluate_kwargs = mock_profile_gate_service.evaluate_gate.call_args.kwargs
    assert evaluate_kwargs["intent"] == "profile_completion"

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert assistant_kwargs["metadata"]["intent"] == "profile_completion"


@pytest.mark.asyncio
async def test_send_message_chat_not_found(chat_service, mock_chat_repo):
    """Test sending message to non-existent chat."""
    mock_chat_repo.get_by_id_with_user.return_value = None

    with pytest.raises(Exception) as exc_info:
        await chat_service.send_message(
            user_id="user-456",
            chat_id="nonexistent",
            content="Hello!",
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_send_message_not_owner(chat_service, mock_chat_repo, sample_chat):
    """Test sending message to chat owned by another user."""
    mock_chat_repo.get_by_id_with_user.return_value = {
        **sample_chat,
        "user_id": "different-user",
    }

    with pytest.raises(Exception) as exc_info:
        await chat_service.send_message(
            user_id="user-456",
            chat_id="chat-123",
            content="Hello!",
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_send_message_deleted_chat(chat_service, mock_chat_repo, sample_chat):
    """Test sending message to a deleted chat."""
    mock_chat_repo.get_by_id_with_user.return_value = {
        **sample_chat,
        "deleted_at": datetime.now(timezone.utc),
    }

    with pytest.raises(Exception) as exc_info:
        await chat_service.send_message(
            user_id="user-456",
            chat_id="chat-123",
            content="Hello!",
        )

    assert exc_info.value.status_code == 404


# ── List Chats Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_chats_pagination(chat_service, mock_chat_repo, sample_chat):
    """Test listing chats with pagination."""
    chats = [sample_chat]
    mock_chat_repo.list_by_user.return_value = (chats, 1)

    result = await chat_service.list_chats(user_id="user-456", limit=20)

    assert result["chats"] == chats
    assert result["total_count"] == 1
    mock_chat_repo.list_by_user.assert_called_once()


@pytest.mark.asyncio
async def test_list_chats_empty(chat_service, mock_chat_repo):
    """Test that empty list is returned when no chats."""
    mock_chat_repo.list_by_user.return_value = ([], 0)

    result = await chat_service.list_chats(user_id="user-456")

    assert result["chats"] == []
    assert result["total_count"] == 0


@pytest.mark.asyncio
async def test_list_chats_with_cursor(chat_service, mock_chat_repo, sample_chat):
    """Test listing chats with cursor pagination."""
    cursor_dt = datetime.now(timezone.utc)
    cursor = base64.b64encode(cursor_dt.isoformat().encode()).decode()

    mock_chat_repo.list_by_user.return_value = ([sample_chat], 1)

    result = await chat_service.list_chats(user_id="user-456", cursor=cursor)

    assert result["chats"] == [sample_chat]
    mock_chat_repo.list_by_user.assert_called_once()


@pytest.mark.asyncio
async def test_list_chats_invalid_cursor(chat_service):
    """Test that invalid cursor raises 400."""
    with pytest.raises(Exception) as exc_info:
        await chat_service.list_chats(user_id="user-456", cursor="invalid-cursor")

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_list_chats_starred_true(chat_service, mock_chat_repo, sample_chat):
    """Test listing only starred chats (starred=True filter)."""
    starred_chat = {**sample_chat, "is_starred": True}
    mock_chat_repo.list_by_user.return_value = ([starred_chat], 1)

    result = await chat_service.list_chats(user_id="user-456", starred=True)

    assert result["chats"] == [starred_chat]
    assert result["total_count"] == 1
    mock_chat_repo.list_by_user.assert_called_once()
    _, call_kwargs = mock_chat_repo.list_by_user.call_args
    assert call_kwargs["starred"] is True


@pytest.mark.asyncio
async def test_list_chats_starred_false(chat_service, mock_chat_repo, sample_chat):
    """Test listing only non-starred chats (starred=False filter)."""
    non_starred_chat = {**sample_chat, "is_starred": False}
    mock_chat_repo.list_by_user.return_value = ([non_starred_chat], 1)

    result = await chat_service.list_chats(user_id="user-456", starred=False)

    assert result["chats"] == [non_starred_chat]
    assert result["total_count"] == 1
    mock_chat_repo.list_by_user.assert_called_once()
    _, call_kwargs = mock_chat_repo.list_by_user.call_args
    assert call_kwargs["starred"] is False


@pytest.mark.asyncio
async def test_list_chats_starred_none(chat_service, mock_chat_repo, sample_chat):
    """Test listing all chats when starred=None (no filter)."""
    mock_chat_repo.list_by_user.return_value = ([sample_chat], 1)

    result = await chat_service.list_chats(user_id="user-456", starred=None)

    assert result["chats"] == [sample_chat]
    mock_chat_repo.list_by_user.assert_called_once()
    _, call_kwargs = mock_chat_repo.list_by_user.call_args
    assert call_kwargs["starred"] is None


# ── Get Chat Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_chat_success(chat_service, mock_chat_repo, sample_chat):
    """Test getting a chat by ID."""
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat

    result = await chat_service.get_chat(user_id="user-456", chat_id="chat-123")

    assert result["id"] == "chat-123"


@pytest.mark.asyncio
async def test_get_chat_not_found(chat_service, mock_chat_repo):
    """Test getting non-existent chat returns 404."""
    mock_chat_repo.get_by_id_with_user.return_value = None

    with pytest.raises(Exception) as exc_info:
        await chat_service.get_chat(user_id="user-456", chat_id="nonexistent")

    assert exc_info.value.status_code == 404


# ── Update Chat Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_chat_title_success(chat_service, mock_chat_repo, sample_chat):
    """Test updating chat title."""
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "title": "New Title"}

    result = await chat_service.update_chat(
        user_id="user-456",
        chat_id="chat-123",
        title="New Title",
    )

    assert result["title"] == "New Title"
    mock_chat_repo.update_title.assert_called_once_with("chat-123", "New Title")


@pytest.mark.asyncio
async def test_update_chat_starred(chat_service, mock_chat_repo, sample_chat):
    """Test starring a chat."""
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "is_starred": True}

    result = await chat_service.update_chat(
        user_id="user-456",
        chat_id="chat-123",
        is_starred=True,
    )

    assert result["is_starred"] is True
    mock_chat_repo.update_starred.assert_called_once_with("chat-123", True)


@pytest.mark.asyncio
async def test_update_chat_move_to_project(chat_service, mock_chat_repo, mock_project_repo, sample_chat):
    """Test moving a chat to a project."""
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_project_repo.exists_for_user.return_value = True
    mock_chat_repo.get_by_id.return_value = {
        **sample_chat,
        "project_id": "proj-123",
    }

    result = await chat_service.update_chat(
        user_id="user-456",
        chat_id="chat-123",
        project_id="proj-123",
    )

    assert result["project_id"] == "proj-123"
    mock_chat_repo.update_project.assert_called_once_with("chat-123", "proj-123")
    mock_project_repo.increment_chat_count.assert_called_once_with("proj-123", 1)


@pytest.mark.asyncio
async def test_update_chat_remove_from_project(chat_service, mock_chat_repo, mock_project_repo, sample_chat):
    """Test removing a chat from a project."""
    sample_chat_with_project = {**sample_chat, "project_id": "proj-123"}
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat_with_project
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "project_id": None}

    result = await chat_service.update_chat(
        user_id="user-456",
        chat_id="chat-123",
        remove_from_project=True,
    )

    assert result["project_id"] is None
    mock_chat_repo.update_project.assert_called_once_with("chat-123", None)
    mock_project_repo.increment_chat_count.assert_called_once_with("proj-123", -1)


# ── Delete Chat Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_chat_soft_delete(chat_service, mock_chat_repo, sample_chat):
    """Test soft deleting a chat."""
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.soft_delete.return_value = True

    await chat_service.delete_chat(user_id="user-456", chat_id="chat-123")

    mock_chat_repo.soft_delete.assert_called_once_with("chat-123")


@pytest.mark.asyncio
async def test_delete_chat_not_owner(chat_service, mock_chat_repo, sample_chat):
    """Test deleting chat owned by another user."""
    mock_chat_repo.get_by_id_with_user.return_value = {
        **sample_chat,
        "user_id": "different-user",
    }

    with pytest.raises(Exception) as exc_info:
        await chat_service.delete_chat(user_id="user-456", chat_id="chat-123")

    assert exc_info.value.status_code == 404


# ── Get Messages Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_messages_success(chat_service, mock_chat_repo, mock_message_repo, sample_chat, sample_message):
    """Test getting message history."""
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_message_repo.list_by_chat.return_value = [sample_message]

    result = await chat_service.get_messages(
        user_id="user-456",
        chat_id="chat-123",
        limit=50,
    )

    assert len(result["messages"]) == 1
    mock_message_repo.list_by_chat.assert_called_once()


@pytest.mark.asyncio
async def test_get_messages_order_desc(chat_service, mock_chat_repo, mock_message_repo, sample_chat, sample_message):
    """Test getting messages in descending order."""
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_message_repo.list_by_chat.return_value = [sample_message]

    await chat_service.get_messages(
        user_id="user-456",
        chat_id="chat-123",
        order="desc",
    )

    mock_message_repo.list_by_chat.assert_called_once()
    call_args = mock_message_repo.list_by_chat.call_args
    assert call_args.kwargs.get("order") == "desc"


# ── Auto Title Tests ─────────────────────────────────────────────────────────


def test_generate_title_from_message_short(chat_service):
    """Test title generation from short message."""
    title = chat_service._generate_title_from_message("Hello world")
    assert title == "Hello world"


def test_generate_title_from_message_long(chat_service):
    """Test title generation truncates long messages."""
    long_message = "This is a very long message that should be truncated because it exceeds the maximum title length"
    title = chat_service._generate_title_from_message(long_message)

    assert len(title) <= 53
    assert title.endswith("...")


def test_generate_title_from_message_word_boundary(chat_service):
    """Test title truncation respects word boundaries."""
    message = "This is a test message that will definitely exceed the max title length limit"
    title = chat_service._generate_title_from_message(message)

    assert not title[:-3].endswith(" ")


def test_generate_placeholder_response(chat_service):
    """Test placeholder response is generated."""
    response = chat_service._generate_placeholder_response("Hello")

    assert "Ouroboros" in response
    assert "scholarships" in response.lower()
