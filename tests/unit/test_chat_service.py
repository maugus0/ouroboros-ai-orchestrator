"""Unit tests for ChatService."""

# Pytest injects fixture names as test parameters (redefined-outer-name).
# Tests call private helpers on the service under test (protected-access).
# pylint: disable=redefined-outer-name,protected-access,too-many-lines

import base64
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.clients.agent_client import AgentClientError
from app.services.chat_service import ChatService

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_chat_repo():
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
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.list_by_chat = AsyncMock()
    repo.count_by_chat = AsyncMock()
    return repo


@pytest.fixture
def mock_project_repo():
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
    service = MagicMock()
    service.evaluate_gate = AsyncMock()
    service.collect_profile_updates_from_chat = AsyncMock()
    service.persist_profile_updates_from_chat = AsyncMock()
    service.get_profile_clarifications = AsyncMock()
    service.submit_profile_clarification_answers = AsyncMock()
    return service


@pytest.fixture
def mock_intent_registry_service():
    service = MagicMock()
    service.detect_intent = MagicMock(return_value="program_discovery")
    service.get_policy = MagicMock(return_value={"agent": "program-discovery"})
    return service


@pytest.fixture
def mock_agent_availability_service():
    service = MagicMock()
    service.is_agent_available = AsyncMock(return_value=True)
    return service


@pytest.fixture
def mock_program_discovery_client():
    client = MagicMock()
    client.probe_health = AsyncMock(return_value={"status": "ok"})
    client.ask_question = AsyncMock(
        return_value={
            "answer": "Here are some programs that match your criteria including MSc Artificial Intelligence.",
            "programs": [],
            "agent_reasoning": {
                "approach": "Searched for programs matching user criteria",
                "confidence": 0.9,
            },
        }
    )
    return client


@pytest.fixture
def mock_application_support_client():
    """Create a mock application-support client."""
    client = MagicMock()
    client.generate_sop = AsyncMock(return_value={"data": {"content": "Generated SOP content"}})
    client.generate_cover_letter = AsyncMock(return_value={"data": {"content": "Generated cover letter"}})
    client.create_checklist = AsyncMock(
        return_value={
            "data": {
                "items": [
                    {"description": "Prepare SOP"},
                    {"description": "Request recommendation letters"},
                ]
            }
        }
    )
    client.list_deadlines = AsyncMock(return_value={"data": []})
    return client


@pytest.fixture
def mock_scholarship_discovery_client():
    client = MagicMock()
    client.search_scholarships = AsyncMock(
        return_value={
            "success": True,
            "data": [
                {
                    "id": "scholarship-1",
                    "name": "Global Masters Scholarship",
                    "provider": "UCL",
                    "funding_amount": 15000,
                    "currency": "GBP",
                }
            ],
            "total": 1,
            "agent_reasoning": {
                "approach": "Filtered scholarships based on student profile",
                "confidence": 0.85,
            },
        }
    )
    return client


@pytest.fixture
def mock_result_aggregation_service():
    service = MagicMock()
    service.discover = AsyncMock(
        return_value={
            "workflow_id": "agg-wf-1",
            "status": "success",
            "version": 5,
            "dashboard": {
                "workflow_id": "agg-wf-1",
                "status": "success",
                "version": 5,
                "programs": {
                    "items": [
                        {
                            "id": "program-1",
                            "program_name": "MSc Artificial Intelligence",
                            "institution_name": "Imperial College London",
                            "institution_country": "United Kingdom",
                            "match": {"match_score": 88.2},
                        }
                    ],
                    "total": 1,
                },
                "scholarships": {
                    "items": [
                        {
                            "id": "scholarship-1",
                            "name": "Global Masters Scholarship",
                            "provider": "UCL",
                            "funding_amount": 15000,
                            "currency": "GBP",
                            "match": {"match_score": "82.6"},
                        }
                    ],
                    "total": 1,
                },
                "matches": {"items": [], "total": 0},
                "errors": [],
            },
        }
    )
    return service


@pytest.fixture
def chat_service(
    mock_chat_repo,
    mock_message_repo,
    mock_project_repo,
    mock_profile_gate_service,
    mock_intent_registry_service,
    mock_agent_availability_service,
    mock_program_discovery_client,
    mock_scholarship_discovery_client,
    mock_application_support_client,
    mock_result_aggregation_service,
):
    ChatService._RESPONSE_CACHE.clear()
    return ChatService(
        chat_repo=mock_chat_repo,
        message_repo=mock_message_repo,
        project_repo=mock_project_repo,
        profile_gate_service=mock_profile_gate_service,
        intent_registry_service=mock_intent_registry_service,
        agent_availability_service=mock_agent_availability_service,
        program_discovery_client=mock_program_discovery_client,
        scholarship_discovery_client=mock_scholarship_discovery_client,
        application_support_client=mock_application_support_client,
        result_aggregation_service=mock_result_aggregation_service,
    )


@pytest.fixture
def sample_chat():
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
    mock_program_discovery_client,
):
    """Test sending a discovery message uses PDA for rich response and saves to dashboard async."""
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
        content="Find programs for me",
    )

    assert "user_message" in result
    assert "assistant_message" in result
    assert "chat" in result
    assert mock_message_repo.create.call_count == 2
    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    # Hybrid approach: Response comes from PDA (rich response with agent_reasoning)
    assert "MSc Artificial Intelligence" in assistant_kwargs["content"]
    # PDA handler is called for the rich response
    mock_program_discovery_client.ask_question.assert_awaited_once()
    # Dashboard save happens async (may or may not complete before assertion)
    # The key is that PDA is the primary handler for chat response


@pytest.mark.asyncio
async def test_send_message_reuses_cached_response_for_repeated_turns(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
    mock_program_discovery_client,
):
    ChatService._RESPONSE_CACHE.clear()
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

    # Hybrid approach: PDA is called once (first call), second call uses cache
    assert mock_program_discovery_client.ask_question.await_count == 1
    assistant_messages = [
        call for call in mock_message_repo.create.call_args_list if call.kwargs.get("role") == "assistant"
    ]
    assert len(assistant_messages) == 2
    # Both responses should contain the PDA response (first from PDA, second from cache)
    assert "MSc Artificial Intelligence" in assistant_messages[-1].kwargs["content"]


@pytest.mark.asyncio
async def test_response_cache_evicts_oldest_entries():
    original_max_entries = ChatService._RESPONSE_CACHE_MAX_ENTRIES
    original_ttl_seconds = ChatService._RESPONSE_CACHE_TTL_SECONDS
    ChatService._RESPONSE_CACHE.clear()
    ChatService._RESPONSE_CACHE_MAX_ENTRIES = 2
    ChatService._RESPONSE_CACHE_TTL_SECONDS = 3600

    try:
        key_one = ChatService._build_response_cache_key(
            "chat-123",
            "first message",
            "program_discovery",
            {"allowed": True, "reason": "profile_complete_for_intent"},
            "program-discovery",
        )
        key_two = ChatService._build_response_cache_key(
            "chat-123",
            "second message",
            "program_discovery",
            {"allowed": True, "reason": "profile_complete_for_intent"},
            "program-discovery",
        )
        key_three = ChatService._build_response_cache_key(
            "chat-123",
            "third message",
            "program_discovery",
            {"allowed": True, "reason": "profile_complete_for_intent"},
            "program-discovery",
        )

        ChatService._set_cached_response(key_one, {"assistant_content": "one", "gate": {"allowed": True}})
        ChatService._set_cached_response(key_two, {"assistant_content": "two", "gate": {"allowed": True}})

        assert ChatService._get_cached_response(key_one)["assistant_content"] == "one"

        ChatService._set_cached_response(key_three, {"assistant_content": "three", "gate": {"allowed": True}})

        assert ChatService._get_cached_response(key_one)["assistant_content"] == "one"
        assert ChatService._get_cached_response(key_two) is None
        assert ChatService._get_cached_response(key_three)["assistant_content"] == "three"
        assert len(ChatService._RESPONSE_CACHE) == 2
    finally:
        ChatService._RESPONSE_CACHE.clear()
        ChatService._RESPONSE_CACHE_MAX_ENTRIES = original_max_entries
        ChatService._RESPONSE_CACHE_TTL_SECONDS = original_ttl_seconds


@pytest.mark.asyncio
async def test_send_message_profile_gate_denied(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
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
async def test_post_assistant_notice_infers_active_profile_slot_metadata(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
):
    assistant_notice = {
        "id": "msg-asst-002",
        "chat_id": "chat-123",
        "role": "assistant",
        "content": "What is your target degree level?",
        "metadata": {},
        "created_at": datetime.now(timezone.utc),
    }
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 1}
    mock_message_repo.create.return_value = assistant_notice

    await chat_service.post_assistant_notice(
        user_id="user-456",
        chat_id="chat-123",
        content="What is your target degree level?",
        metadata={"source": "profile_upload_followup"},
    )

    _, kwargs = mock_message_repo.create.call_args
    assert kwargs["metadata"]["active_profile_slot"] == {
        "field": "target_degree_level",
        "label": "target degree level",
        "expected_type": "degree_level",
        "source": "message_inference",
    }


@pytest.mark.asyncio
async def test_send_message_profile_completion_returns_readiness_summary(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
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
    # Hybrid approach: Response comes from PDA with rich content
    assert "MSc Artificial Intelligence" in assistant_kwargs["content"]
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
    """Program discovery uses PDA handler for rich response, saves to dashboard async."""
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
    # Hybrid approach: Response comes from PDA handler (rich response with agent_reasoning)
    assert "MSc Artificial Intelligence" in assistant_kwargs["content"]
    # PDA handler is called for the rich response
    mock_program_discovery_client.ask_question.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_scholarship_search_uses_sda_handler(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
    mock_scholarship_discovery_client,
):
    """Scholarship search uses SDA handler for rich response, saves to dashboard async."""
    mock_profile_gate_service.evaluate_gate.return_value = {
        "user_id": "user-456",
        "completed": True,
        "missing_fields": [],
        "updated_at": None,
        "allowed": True,
        "reason": "profile_complete_for_intent",
    }
    chat_service.intent_registry_service.detect_intent.return_value = "scholarship_search"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "scholarship-discovery"}
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="Find scholarships for a master degree in Singapore",
    )

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    # Hybrid approach: Response comes from SDA handler (rich response with agent_reasoning)
    assert "Global Masters Scholarship" in assistant_kwargs["content"]
    # SDA handler is called for the rich response
    mock_scholarship_discovery_client.search_scholarships.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_program_discovery_stays_intent_led_when_profile_incomplete(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    chat_service.intent_registry_service.detect_intent.return_value = "program_discovery"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "program-discovery"}

    mock_profile_gate_service.evaluate_gate.side_effect = [
        {
            "user_id": "user-456",
            "completed": False,
            "missing_fields": ["current_degree_level", "target_degree_level"],
            "missing_required_fields": ["current_degree_level", "target_degree_level"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
        },
        {
            "user_id": "user-456",
            "completed": False,
            "missing_fields": ["current_degree_level"],
            "missing_required_fields": ["current_degree_level"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
        },
    ]
    mock_profile_gate_service.collect_profile_updates_from_chat.return_value = {
        "applied_fields": ["target_degree_level"],
    }
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message
    mock_message_repo.list_by_chat.return_value = []

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="I want to discover master program",
    )

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert assistant_kwargs["metadata"]["intent"] == "program_discovery"
    assert assistant_kwargs["content"] == (
        "I can help discover programs, but I need to finish your profile first. "
        "Please share your current degree level."
    )
    assert "saved your target degree level" not in assistant_kwargs["content"]


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
async def test_send_message_application_support_intent_calls_client(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
    mock_application_support_client,
):
    """Application-planning turns should delegate to application-support once the gate passes."""
    chat_service.intent_registry_service.detect_intent.return_value = "application_planning"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "application-support"}
    mock_profile_gate_service.evaluate_gate.return_value = {
        "user_id": "user-456",
        "completed": True,
        "missing_fields": [],
        "optional_missing_fields": [],
        "updated_at": "2026-04-12T00:00:00",
        "allowed": True,
        "reason": "profile_complete_for_intent",
        "intent": "application_planning",
        "missing_required_fields": [],
        "missing_optional_fields": [],
    }
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="Write an SOP for NUS Master of Computing",
    )

    mock_application_support_client.generate_sop.assert_awaited_once()
    call_args = mock_application_support_client.generate_sop.await_args
    assert call_args.args[0] == "user-456"
    assert call_args.args[1]["target_program"]["program_name"] == "NUS Master of Computing"
    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert assistant_kwargs["content"] == "Generated SOP content"


@pytest.mark.asyncio
async def test_send_message_application_support_missing_sop_context_asks_for_target(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
    mock_application_support_client,
):
    """SOP requests without target context should not call downstream with invalid payloads."""
    chat_service.intent_registry_service.detect_intent.return_value = "application_planning"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "application-support"}
    mock_profile_gate_service.evaluate_gate.return_value = {
        "user_id": "user-456",
        "completed": True,
        "missing_fields": [],
        "optional_missing_fields": [],
        "updated_at": "2026-04-12T00:00:00",
        "allowed": True,
        "reason": "profile_complete_for_intent",
        "intent": "application_planning",
        "missing_required_fields": [],
        "missing_optional_fields": [],
    }
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="Write my SOP",
    )

    mock_application_support_client.generate_sop.assert_not_awaited()
    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert "target university or program" in assistant_kwargs["content"]


@pytest.mark.asyncio
async def test_send_message_application_support_failure_returns_graceful_response(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
    mock_application_support_client,
):
    """Downstream application-support failures should not crash the chat turn."""
    chat_service.intent_registry_service.detect_intent.return_value = "application_planning"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "application-support"}
    mock_profile_gate_service.evaluate_gate.return_value = {
        "user_id": "user-456",
        "completed": True,
        "missing_fields": [],
        "optional_missing_fields": [],
        "updated_at": "2026-04-12T00:00:00",
        "allowed": True,
        "reason": "profile_complete_for_intent",
        "intent": "application_planning",
        "missing_required_fields": [],
        "missing_optional_fields": [],
    }
    mock_application_support_client.create_checklist.side_effect = AgentClientError(
        service_name="application-support",
        message="application-support request failed",
        status_code=503,
    )
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="Create an application checklist for NUS",
    )

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert "application-support service is temporarily unavailable" in assistant_kwargs["content"]


@pytest.mark.asyncio
async def test_send_message_out_of_scope_is_overridden_during_profile_clarification(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
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
async def test_send_message_program_like_slot_answer_stays_in_profile_completion(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    chat_service.intent_registry_service.detect_intent.return_value = "program_discovery"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "student-profile"}

    mock_profile_gate_service.evaluate_gate.side_effect = [
        {
            "user_id": "user-456",
            "completed": False,
            "missing_fields": ["intended_field_of_study"],
            "missing_required_fields": ["intended_field_of_study"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
        },
        {
            "user_id": "user-456",
            "completed": False,
            "missing_fields": ["target_study_country"],
            "missing_required_fields": ["target_study_country"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
        },
    ]
    mock_profile_gate_service.collect_profile_updates_from_chat.return_value = {
        "applied_fields": ["intended_field_of_study"],
    }
    mock_profile_gate_service.persist_profile_updates_from_chat.return_value = None
    mock_profile_gate_service.get_profile_clarifications.return_value = {
        "profile_id": "profile-1",
        "clarification_queue": [],
    }
    mock_profile_gate_service.submit_profile_clarification_answers.return_value = None

    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message
    mock_message_repo.list_by_chat.return_value = [
        {
            "id": "assistant-prev-1",
            "role": "assistant",
            "content": "Great, I saved your GPA and GPA scale. Next, please share your intended field of study.",
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
        content="Computer Science",
    )

    evaluate_kwargs = mock_profile_gate_service.evaluate_gate.call_args.kwargs
    assert evaluate_kwargs["intent"] == "profile_completion"

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert assistant_kwargs["metadata"]["intent"] == "profile_completion"
    assert "Great, I saved your intended field of study." in assistant_kwargs["content"]
    assert "Next, please share your preferred study country." in assistant_kwargs["content"]


@pytest.mark.asyncio
async def test_send_message_uses_clarification_question_from_student_profile(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    chat_service.intent_registry_service.detect_intent.return_value = "profile_completion"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "student-profile"}

    mock_profile_gate_service.evaluate_gate.side_effect = [
        {
            "user_id": "user-456",
            "profile_id": "profile-1",
            "completed": False,
            "missing_fields": ["current_degree_level"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
        },
        {
            "user_id": "user-456",
            "profile_id": "profile-1",
            "completed": False,
            "missing_fields": ["current_degree_level"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
        },
    ]
    mock_profile_gate_service.collect_profile_updates_from_chat.return_value = {"applied_fields": []}
    mock_profile_gate_service.get_profile_clarifications.return_value = {
        "profile_id": "profile-1",
        "status": "needs_clarification",
        "clarification_queue": [{"field": "current_degree_level", "question": "What is your current degree level?"}],
        "react_decision_trace": {"current_degree_level": {"decision": "clarify", "reason": "missing_or_unknown"}},
    }

    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message
    mock_message_repo.list_by_chat.return_value = []

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="master",
    )

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert assistant_kwargs["content"] == (
        "I can help with scholarships and program searches, but I need to finish your profile first. "
        "Let's start with your current degree level. Once you send that, I'll ask for the next detail."
    )
    assert assistant_kwargs["metadata"]["profile_gate"]["profile_id"] == "profile-1"


@pytest.mark.asyncio
async def test_send_message_binary_reply_routes_to_react_clarification_submission(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    chat_service.intent_registry_service.detect_intent.return_value = "profile_completion"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "student-profile"}

    mock_profile_gate_service.evaluate_gate.side_effect = [
        {
            "user_id": "user-456",
            "profile_id": "profile-1",
            "completed": False,
            "missing_fields": ["publications", "target_degree_level"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
        },
        {
            "user_id": "user-456",
            "profile_id": "profile-1",
            "completed": False,
            "missing_fields": ["target_degree_level"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
        },
    ]
    mock_profile_gate_service.get_profile_clarifications.return_value = {
        "profile_id": "profile-1",
        "status": "needs_clarification",
        "clarification_queue": [
            {
                "field": "publications",
                "question": "Do you have publications? Please provide title, venue, and year if available.",
            }
        ],
    }
    mock_profile_gate_service.submit_profile_clarification_answers.return_value = {
        "profile_id": "profile-1",
        "applied_fields": ["publications"],
        "clarification_queue": [
            {
                "field": "target_degree_level",
                "question": "What is your target degree level?",
            }
        ],
    }

    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message
    mock_message_repo.list_by_chat.return_value = [
        {
            "id": "assistant-prev-1",
            "role": "assistant",
            "content": "Do you have publications? Please provide title, venue, and year if available.",
            "metadata": {
                "source": "profile_upload_followup",
                "profile_gate": {
                    "allowed": False,
                    "reason": "profile_incomplete_for_intent",
                },
            },
        }
    ]

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="No",
    )

    mock_profile_gate_service.collect_profile_updates_from_chat.assert_not_awaited()
    mock_profile_gate_service.submit_profile_clarification_answers.assert_awaited_once()
    submit_kwargs = mock_profile_gate_service.submit_profile_clarification_answers.call_args.kwargs
    assert submit_kwargs["answers"] == [{"field": "publications", "value": "No"}]

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert assistant_kwargs["content"] == "Great, I saved your publications. What is your target degree level?"


@pytest.mark.asyncio
async def test_send_message_non_binary_degree_reply_routes_to_react_clarification_submission(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    chat_service.intent_registry_service.detect_intent.return_value = "profile_completion"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "student-profile"}

    mock_profile_gate_service.evaluate_gate.side_effect = [
        {
            "user_id": "user-456",
            "profile_id": "profile-1",
            "completed": False,
            "missing_fields": ["current_degree_level"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
        },
        {
            "user_id": "user-456",
            "profile_id": "profile-1",
            "completed": False,
            "missing_fields": ["target_degree_level"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
        },
    ]
    mock_profile_gate_service.get_profile_clarifications.return_value = {
        "profile_id": "profile-1",
        "status": "needs_clarification",
        "clarification_queue": [
            {
                "field": "current_degree_level",
                "question": "What is your current degree level?",
            }
        ],
    }
    mock_profile_gate_service.submit_profile_clarification_answers.return_value = {
        "profile_id": "profile-1",
        "applied_fields": ["current_degree_level"],
        "clarification_queue": [
            {
                "field": "target_degree_level",
                "question": "What is your target degree level?",
            }
        ],
    }

    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message
    mock_message_repo.list_by_chat.return_value = [
        {
            "id": "assistant-prev-1",
            "role": "assistant",
            "content": "What is your current degree level?",
            "metadata": {
                "profile_gate": {
                    "allowed": False,
                    "reason": "profile_incomplete_for_intent",
                },
            },
        }
    ]

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="master degree",
    )

    mock_profile_gate_service.collect_profile_updates_from_chat.assert_not_awaited()
    mock_profile_gate_service.submit_profile_clarification_answers.assert_awaited_once()
    submit_kwargs = mock_profile_gate_service.submit_profile_clarification_answers.call_args.kwargs
    assert submit_kwargs["answers"] == [{"field": "current_degree_level", "value": "master degree"}]

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert assistant_kwargs["content"] == "Great, I saved your current degree level. What is your target degree level?"


@pytest.mark.asyncio
async def test_send_message_slot_bound_reply_persists_active_prompt_field_first(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    chat_service.intent_registry_service.detect_intent.return_value = "profile_completion"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "student-profile"}

    mock_profile_gate_service.evaluate_gate.side_effect = [
        {
            "user_id": "user-456",
            "completed": False,
            "missing_fields": ["current_degree_level", "target_degree_level"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
        },
        {
            "user_id": "user-456",
            "completed": False,
            "missing_fields": ["target_degree_level"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
        },
    ]
    mock_profile_gate_service.persist_profile_updates_from_chat.return_value = {
        "applied_fields": ["current_degree_level"],
    }

    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message
    mock_message_repo.list_by_chat.return_value = [
        {
            "id": "assistant-prev-1",
            "role": "assistant",
            "content": "Let's start with your current degree level. Once you send that, I'll ask for the next detail.",
            "metadata": {
                "profile_gate": {
                    "allowed": False,
                    "reason": "profile_incomplete_for_intent",
                },
                "active_profile_slot": {
                    "field": "current_degree_level",
                    "label": "current degree level",
                    "expected_type": "degree_level",
                    "source": "profile_gate_missing_field",
                },
            },
        }
    ]

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="master degree",
    )

    mock_profile_gate_service.persist_profile_updates_from_chat.assert_awaited_once()
    persist_kwargs = mock_profile_gate_service.persist_profile_updates_from_chat.call_args.kwargs
    assert persist_kwargs["fields"] == {"current_degree_level": "master"}
    mock_profile_gate_service.collect_profile_updates_from_chat.assert_not_awaited()

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert (
        assistant_kwargs["content"]
        == "Great, I saved your current degree level. Next, please share your target degree level."
    )
    assert assistant_kwargs["metadata"]["active_profile_slot"] == {
        "field": "target_degree_level",
        "label": "target degree level",
        "expected_type": "degree_level",
        "source": "message_inference",
    }


@pytest.mark.asyncio
async def test_send_message_chat_not_found(chat_service, mock_chat_repo):
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
    chats = [sample_chat]
    mock_chat_repo.list_by_user.return_value = (chats, 1)

    result = await chat_service.list_chats(user_id="user-456", limit=20)

    assert result["chats"] == chats
    assert result["total_count"] == 1
    mock_chat_repo.list_by_user.assert_called_once()


@pytest.mark.asyncio
async def test_list_chats_empty(chat_service, mock_chat_repo):
    mock_chat_repo.list_by_user.return_value = ([], 0)

    result = await chat_service.list_chats(user_id="user-456")

    assert result["chats"] == []
    assert result["total_count"] == 0


@pytest.mark.asyncio
async def test_list_chats_with_cursor(chat_service, mock_chat_repo, sample_chat):
    cursor_dt = datetime.now(timezone.utc)
    cursor = base64.b64encode(cursor_dt.isoformat().encode()).decode()

    mock_chat_repo.list_by_user.return_value = ([sample_chat], 1)

    result = await chat_service.list_chats(user_id="user-456", cursor=cursor)

    assert result["chats"] == [sample_chat]
    mock_chat_repo.list_by_user.assert_called_once()


@pytest.mark.asyncio
async def test_list_chats_invalid_cursor(chat_service):
    with pytest.raises(Exception) as exc_info:
        await chat_service.list_chats(user_id="user-456", cursor="invalid-cursor")

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_list_chats_starred_true(chat_service, mock_chat_repo, sample_chat):
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
    mock_chat_repo.list_by_user.return_value = ([sample_chat], 1)

    result = await chat_service.list_chats(user_id="user-456", starred=None)

    assert result["chats"] == [sample_chat]
    mock_chat_repo.list_by_user.assert_called_once()
    _, call_kwargs = mock_chat_repo.list_by_user.call_args
    assert call_kwargs["starred"] is None


# ── Get Chat Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_chat_success(chat_service, mock_chat_repo, sample_chat):
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat

    result = await chat_service.get_chat(user_id="user-456", chat_id="chat-123")

    assert result["id"] == "chat-123"


@pytest.mark.asyncio
async def test_get_chat_not_found(chat_service, mock_chat_repo):
    mock_chat_repo.get_by_id_with_user.return_value = None

    with pytest.raises(Exception) as exc_info:
        await chat_service.get_chat(user_id="user-456", chat_id="nonexistent")

    assert exc_info.value.status_code == 404


# ── Update Chat Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_chat_title_success(chat_service, mock_chat_repo, sample_chat):
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
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.soft_delete.return_value = True

    await chat_service.delete_chat(user_id="user-456", chat_id="chat-123")

    mock_chat_repo.soft_delete.assert_called_once_with("chat-123")


@pytest.mark.asyncio
async def test_delete_chat_not_owner(chat_service, mock_chat_repo, sample_chat):
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


def test_generate_title_from_message_long(chat_service):
    long_message = "This is a very long message that should be truncated because it exceeds the maximum title length"
    title = chat_service._generate_title_from_message(long_message)

    assert len(title) <= 53
    assert title.endswith("...")


def test_generate_title_from_message_word_boundary(chat_service):
    message = "This is a test message that will definitely exceed the max title length limit"
    title = chat_service._generate_title_from_message(message)

    assert not title[:-3].endswith(" ")


def test_generate_placeholder_response(chat_service):
    response = chat_service._generate_placeholder_response("Hello")

    assert "Ouroboros" in response
    assert "scholarships" in response.lower()


# ── Explainability Metadata Tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_message_metadata_includes_orchestrator_thoughts_gate_decision_routing_decision(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    """orchestrator_thoughts, gate_decision, and routing_decision must be present
    in the assistant message metadata on every successful send_message turn."""
    chat_service.intent_registry_service.detect_intent.return_value = "program_discovery"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "program-discovery"}
    mock_profile_gate_service.evaluate_gate.return_value = {
        "user_id": "user-456",
        "completed": True,
        "missing_fields": [],
        "missing_required_fields": [],
        "missing_optional_fields": [],
        "updated_at": "2026-04-12T00:00:00",
        "allowed": True,
        "reason": "profile_complete_for_intent",
        "intent": "program_discovery",
    }
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="Find programs in Singapore",
    )

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    meta = assistant_kwargs["metadata"]

    # orchestrator_thoughts shape
    ot = meta["orchestrator_thoughts"]
    assert ot["intent"] == "program_discovery"
    assert isinstance(ot["intent_confidence"], float)
    assert "reasoning" not in ot

    # gate_decision shape
    gd = meta["gate_decision"]
    assert gd["allowed"] is True
    assert gd["status"] == "COMPLETE"
    assert isinstance(gd["missing_fields"], list)
    assert isinstance(gd["reason"], str)

    # routing_decision shape
    rd = meta["routing_decision"]
    assert rd["selected_agent"] == "program-discovery"
    assert isinstance(rd["routing_reason"], str)
    assert isinstance(rd["confidence"], float)
    assert isinstance(rd["alternative_agents"], list)

    # Hybrid approach: agent_reasoning is now included from the PDA/SDA response
    # This is the key improvement - rich agent reasoning is preserved in metadata
    assert "agent_reasoning" in meta
    assert meta["agent_reasoning"]["approach"] == "Searched for programs matching user criteria"


@pytest.mark.asyncio
async def test_send_message_metadata_includes_agent_reasoning_when_gate_denied(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    """When the profile gate denies the request, agent_reasoning must be present
    with approach, decision_factors, next_field, and confidence."""
    chat_service.intent_registry_service.detect_intent.return_value = "profile_completion"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "student-profile"}
    denied_gate = {
        "user_id": "user-456",
        "completed": False,
        "missing_fields": ["email", "gpa"],
        "missing_required_fields": ["email", "gpa"],
        "missing_optional_fields": [],
        "updated_at": "2026-04-12T00:00:00",
        "allowed": False,
        "reason": "profile_incomplete_for_intent",
    }
    mock_profile_gate_service.evaluate_gate.return_value = denied_gate
    mock_profile_gate_service.collect_profile_updates_from_chat.return_value = None
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message
    mock_message_repo.list_by_chat.return_value = []

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="Help me complete my profile",
    )

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    meta = assistant_kwargs["metadata"]

    ar = meta["agent_reasoning"]
    assert isinstance(ar["approach"], str)
    assert isinstance(ar["decision_factors"], list)
    assert len(ar["decision_factors"]) > 0
    assert ar["next_field"] == "email"
    assert isinstance(ar["confidence"], float)
