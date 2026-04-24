"""Unit tests for ChatService."""

# Pytest injects fixture names as test parameters (redefined-outer-name).
# Tests call private helpers on the service under test (protected-access).
# pylint: disable=redefined-outer-name,protected-access,too-many-lines

import asyncio
import base64
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.clients.agent_client import AgentClientError
from app.services.chat_service import ChatService
from app.services.eligibility_service import EligibilityService

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
    client.search_programs = AsyncMock(return_value={"data": []})
    client.search_institutions = AsyncMock(return_value={"data": []})
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
    mock_eligibility_service,
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
        eligibility_service=mock_eligibility_service,
    )


@pytest.fixture
def mock_eligibility_service():
    service = MagicMock(spec=EligibilityService)
    service.evaluate = AsyncMock(
        return_value={
            "match_result": {
                "id": "match-001",
                "user_id": "user-456",
                "entity_type": "program",
                "entity_id": "prog-uuid-1111",
                "match_score": 78.5,
                "score_breakdown": {"gpa": 20, "research_alignment": 30, "language": 15},
                "confidence_level": "high",
                "llm_model_used": "gpt-4o",
                "llm_fallback_used": False,
                "total_processing_time_ms": 340,
            },
            "attribution_report": {"narrative": "Strong research alignment and GPA match the program requirements."},
            "agent_reasoning": {
                "summary": "User is a strong match based on GPA and research background.",
                "strengths": ["GPA above threshold", "Research alignment high"],
                "gaps": [],
                "confidence": "high",
            },
        }
    )
    return service


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
    metadata = assistant_kwargs["metadata"]
    assert metadata["profile_gate"]["reason"] == "intent_agent_unavailable"
    assert metadata["gate_decision"]["status"] == "UNAVAILABLE"
    assert metadata["gate_decision"]["reason"] == "The required agent is currently unavailable."
    assert metadata["routing_decision"]["selected_agent"] == "scholarship-discovery"
    assert metadata["routing_decision"]["confidence"] == 0.92
    assert metadata["agent_reasoning"]["approach"] == "Pause domain routing until the mapped agent is available."
    assert metadata["agent_reasoning"]["next_field"] is None


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
async def test_send_message_gate_blocked_application_support_sets_pending_context(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    """Blocked application-planning turns should preserve the original SOP request for the follow-up slot answer."""
    chat_service.intent_registry_service.detect_intent.return_value = "application_planning"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "application-support"}

    mock_profile_gate_service.evaluate_gate.side_effect = [
        {
            "user_id": "user-456",
            "profile_id": "profile-1",
            "completed": False,
            "missing_fields": [],
            "missing_required_fields": ["enrollment_timeline"],
            "missing_optional_fields": [],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
            "intent": "application_planning",
        },
        {
            "user_id": "user-456",
            "profile_id": "profile-1",
            "completed": False,
            "missing_fields": [],
            "missing_required_fields": ["enrollment_timeline"],
            "missing_optional_fields": [],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
            "intent": "application_planning",
        },
    ]
    mock_profile_gate_service.collect_profile_updates_from_chat.return_value = {"applied_fields": []}
    mock_profile_gate_service.get_profile_clarifications.return_value = {
        "profile_id": "profile-1",
        "status": "needs_clarification",
        "clarification_queue": [
            {
                "field": "enrollment_timeline",
                "question": "Please share your enrollment timeline.",
            }
        ],
    }

    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message
    mock_message_repo.list_by_chat.return_value = []

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="make SOP for NUS Master of Computing",
    )

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert assistant_kwargs["metadata"]["pending_intent"] == "application_planning"
    assert assistant_kwargs["metadata"]["pending_application_support_context"] == {
        "intent": "application_planning",
        "action": "sop",
        "target_program": "NUS Master of Computing",
        "source_message": "make SOP for NUS Master of Computing",
    }


@pytest.mark.asyncio
async def test_build_application_support_response_uses_pending_context_for_slot_reply(
    chat_service,
    mock_application_support_client,
):
    """A slot-only follow-up should continue the original SOP request instead of defaulting to checklist."""
    result, _ = await chat_service._build_application_support_response(
        user_id="user-456",
        chat_id="chat-123",
        user_message="Summer 2027",
        detected_intent="application_planning",
        trace_id="wf-123",
        pending_application_support_context={
            "intent": "application_planning",
            "action": "sop",
            "target_program": "NUS Master of Computing",
            "source_message": "make SOP for NUS Master of Computing",
        },
    )

    assert result == "Generated SOP content"
    mock_application_support_client.generate_sop.assert_awaited_once()
    call_args = mock_application_support_client.generate_sop.await_args
    assert call_args.args[0] == "user-456"
    assert call_args.args[1]["target_program"]["program_name"] == "NUS Master of Computing"
    assert call_args.args[1]["user_preferences"]["source_message"] == "make SOP for NUS Master of Computing"
    assert call_args.args[1]["user_preferences"]["follow_up_message"] == "Summer 2027"


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
async def test_send_message_binary_reply_submits_publications_when_not_missing_required(
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
            "missing_fields": ["gpa", "gpa_scale", "publications"],
            "missing_required_fields": ["gpa", "gpa_scale"],
            "missing_optional_fields": ["target_study_country"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
        },
        {
            "user_id": "user-456",
            "profile_id": "profile-1",
            "completed": False,
            "missing_fields": ["gpa", "gpa_scale"],
            "missing_required_fields": ["gpa", "gpa_scale"],
            "missing_optional_fields": ["target_study_country"],
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
                "field": "gpa",
                "question": "What is your highest GPA?",
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


# ── Eligibility Check Handler Tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_eligibility_check_with_uuid_in_message(
    chat_service,
    mock_eligibility_service,
):
    """When message contains a UUID, use it directly and return score."""
    entity_id = "a1b2c3d4-0000-0000-0000-000000000001"
    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content=f"Am I eligible for program {entity_id}?",
        workflow_run_id="wf-001",
        gate={"allowed": True},
    )

    mock_eligibility_service.evaluate.assert_awaited_once()
    call_args = mock_eligibility_service.evaluate.call_args
    assert call_args.args[0].entity_id == entity_id
    assert call_args.args[0].entity_type == "program"
    assert "78.5" in result["answer"]
    assert result["agent_reasoning"] is not None
    assert result["source"] == "eligibility_engine"


@pytest.mark.asyncio
async def test_handle_eligibility_check_scholarship_keyword_sets_entity_type(
    chat_service,
    mock_eligibility_service,
):
    """Scholarship keyword in message sets entity_type to 'scholarship'."""
    entity_id = "b2c3d4e5-0000-0000-0000-000000000002"
    await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content=f"Do I qualify for this scholarship {entity_id}?",
        workflow_run_id="wf-002",
        gate={"allowed": True},
    )

    call_args = mock_eligibility_service.evaluate.call_args
    assert call_args.args[0].entity_type == "scholarship"


@pytest.mark.asyncio
async def test_handle_eligibility_check_no_entity_returns_clarification(
    chat_service,
    mock_eligibility_service,
    mock_program_discovery_client,
):
    """When no UUID and PDA returns multiple results, handler asks a follow-up."""
    mock_program_discovery_client.search_programs.return_value = {
        "data": [
            {"id": "prog-1", "name": "MSc CS"},
            {"id": "prog-2", "name": "MSc AI"},
        ]
    }

    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content="Am I eligible for a master program?",
        workflow_run_id="wf-003",
        gate={"allowed": True},
    )

    mock_eligibility_service.evaluate.assert_not_awaited()
    assert result["source"] == "orchestrator"
    assert "program" in result["answer"].lower()
    assert result["agent_reasoning"] is None


@pytest.mark.asyncio
async def test_handle_eligibility_check_pda_resolves_single_entity(
    chat_service,
    mock_eligibility_service,
    mock_program_discovery_client,
):
    """When PDA returns exactly one program, auto-select it and evaluate."""
    mock_program_discovery_client.search_programs.return_value = {
        "data": [{"id": "prog-only-1", "name": "MSc Computing"}]
    }

    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content="Am I eligible for MSc Computing at NUS?",
        workflow_run_id="wf-004",
        gate={"allowed": True},
    )

    mock_eligibility_service.evaluate.assert_awaited_once()
    call_args = mock_eligibility_service.evaluate.call_args
    assert call_args.args[0].entity_id == "prog-only-1"
    assert "MSc Computing" in result["answer"]
    assert result["source"] == "eligibility_engine"


@pytest.mark.asyncio
async def test_handle_eligibility_check_consults_program_and_scholarship_agents(
    chat_service,
    mock_eligibility_service,
    mock_program_discovery_client,
    mock_scholarship_discovery_client,
):
    """Eligibility orchestration should consult both PDA and SDA before final evaluation."""
    mock_program_discovery_client.search_programs.return_value = {
        "data": [{"id": "prog-only-1", "name": "MSc Computing"}]
    }
    mock_scholarship_discovery_client.search_scholarships.return_value = {
        "data": [
            {"id": "sch-1", "name": "Scholarship A"},
            {"id": "sch-2", "name": "Scholarship B"},
        ]
    }

    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content="Am I eligible for MSc Computing at NUS?",
        workflow_run_id="wf-consult-both",
        gate={"allowed": True},
    )

    mock_program_discovery_client.search_programs.assert_awaited()
    mock_scholarship_discovery_client.search_scholarships.assert_awaited()
    mock_eligibility_service.evaluate.assert_awaited_once()
    assert result["source"] == "eligibility_engine"


@pytest.mark.asyncio
async def test_handle_eligibility_check_pda_items_shape_resolves_entity(
    chat_service,
    mock_eligibility_service,
    mock_program_discovery_client,
):
    """PDA may return list payload under 'items' with program_name key."""
    mock_program_discovery_client.search_programs.return_value = {
        "items": [{"id": "prog-items-1", "program_name": "Master of Science in Computer Science"}]
    }

    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content="Master of Science in Computer Science",
        workflow_run_id="wf-items-001",
        gate={"allowed": True},
    )

    mock_eligibility_service.evaluate.assert_awaited_once()
    call_args = mock_eligibility_service.evaluate.call_args
    assert call_args.args[0].entity_id == "prog-items-1"
    assert result["source"] == "eligibility_engine"


@pytest.mark.asyncio
async def test_handle_eligibility_check_clarification_reply_picks_best_match(
    chat_service,
    mock_eligibility_service,
    mock_program_discovery_client,
):
    """When is_clarification_reply=True, pick the first result even if PDA returns multiple."""
    mock_program_discovery_client.search_programs.return_value = {
        "data": [
            {"id": "prog-best-1", "name": "NUS Master of Computing"},
            {"id": "prog-other-2", "name": "NUS Master of CS"},
        ]
    }

    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content="NUS Master of Computing",
        workflow_run_id="wf-clarif",
        gate={"allowed": True},
        is_clarification_reply=True,
    )

    mock_eligibility_service.evaluate.assert_awaited_once()
    call_args = mock_eligibility_service.evaluate.call_args
    assert call_args.args[0].entity_id == "prog-best-1"
    assert result["source"] == "eligibility_engine"


@pytest.mark.asyncio
async def test_handle_eligibility_check_not_clarification_reply_multiple_returns_clarification(
    chat_service,
    mock_eligibility_service,
    mock_program_discovery_client,
):
    """When is_clarification_reply=False and PDA returns multiple, still ask for clarification."""
    mock_program_discovery_client.search_programs.return_value = {
        "data": [
            {"id": "prog-a", "name": "MSc Computing"},
            {"id": "prog-b", "name": "MSc CS"},
        ]
    }

    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content="Am I eligible?",
        workflow_run_id="wf-no-clarif",
        gate={"allowed": True},
        is_clarification_reply=False,
    )

    mock_eligibility_service.evaluate.assert_not_awaited()
    assert result["source"] == "orchestrator"
    assert result.get("pending_intent") == "eligibility_check"


@pytest.mark.asyncio
async def test_handle_eligibility_check_clarification_keeps_institution_hint_context(
    chat_service,
    mock_eligibility_service,
    mock_program_discovery_client,
):
    """When unresolved, clarification response should carry institution hint for next turn."""
    mock_program_discovery_client.search_programs.return_value = {"data": []}

    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content="I want to check my eligibility for MIT",
        workflow_run_id="wf-mit-context",
        gate={"allowed": True},
    )

    mock_eligibility_service.evaluate.assert_not_awaited()
    assert result["source"] == "orchestrator"
    assert result.get("pending_intent") == "eligibility_check"
    ctx = result.get("pending_eligibility_context") or {}
    assert ctx.get("institution_hint") == "MIT"


@pytest.mark.asyncio
async def test_handle_eligibility_check_uses_pending_institution_context_on_follow_up(
    chat_service,
    mock_eligibility_service,
    mock_program_discovery_client,
):
    """Follow-up title-only reply should resolve via prior institution hint context."""
    mock_program_discovery_client.search_programs.side_effect = [
        {"data": []},
        {"data": [{"id": "mit-mscs-1", "name": "Master of Science in Computer Science"}]},
    ]
    mock_program_discovery_client.search_institutions.return_value = {
        "data": [{"id": "inst-mit-1", "name": "Massachusetts Institute of Technology"}]
    }

    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content="Master of Science in Computer Science",
        workflow_run_id="wf-mit-followup",
        gate={"allowed": True},
        is_clarification_reply=True,
        pending_eligibility_context={"institution_hint": "MIT", "entity_type": "program"},
    )

    mock_program_discovery_client.search_institutions.assert_awaited_once()
    scoped_call_kwargs = mock_program_discovery_client.search_programs.await_args_list[1].kwargs
    assert scoped_call_kwargs["institution_id"] == "inst-mit-1"

    mock_eligibility_service.evaluate.assert_awaited_once()
    eval_call = mock_eligibility_service.evaluate.call_args
    assert eval_call.args[0].entity_id == "mit-mscs-1"
    assert result["source"] == "eligibility_engine"


@pytest.mark.asyncio
async def test_handle_eligibility_check_formats_wrapped_eligibility_response_payload(
    chat_service,
    mock_eligibility_service,
    mock_program_discovery_client,
):
    """Eligibility responses wrapped in {success,message,data} should still produce score/explainability output."""
    mock_program_discovery_client.search_programs.return_value = {
        "data": [{"id": "mit-mscs-1", "name": "Master of Science in Computer Science"}]
    }
    mock_eligibility_service.evaluate.return_value = {
        "success": True,
        "message": "Evaluation complete",
        "data": {
            "match_result": {
                "match_score": "62.88",
                "confidence_level": "medium",
                "score_breakdown": {"gpa": 20.0},
            },
            "attribution_report": {"narrative": "Profile partially aligns with program expectations."},
            "agent_reasoning": {"approach": "rule-and-llm"},
        },
    }

    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content="MIT Master of Science in Computer Science",
        workflow_run_id="wf-wrapped-eligibility",
        gate={"allowed": True},
        is_clarification_reply=True,
        pending_eligibility_context={"entity_type": "program"},
    )

    assert result["source"] == "eligibility_engine"
    assert "62.88/100" in result["answer"]
    assert "profile partially aligns" in result["answer"].lower()
    assert result["agent_reasoning"] == {"approach": "rule-and-llm"}


@pytest.mark.asyncio
async def test_handle_eligibility_check_clarification_reply_does_not_fallback_to_scholarship(
    chat_service,
    mock_eligibility_service,
    mock_program_discovery_client,
    mock_scholarship_discovery_client,
):
    """Program clarification follow-ups should stay in program flow even if scholarship results exist."""
    mock_program_discovery_client.search_programs.return_value = {"data": []}
    mock_scholarship_discovery_client.search_scholarships.return_value = {
        "data": [{"id": "sch-should-not-use", "name": "Fallback Scholarship"}]
    }

    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content="Master of Science",
        workflow_run_id="wf-no-scholarship-fallback",
        gate={"allowed": True},
        is_clarification_reply=True,
        pending_eligibility_context={"entity_type": "program", "institution_hint": "NUS"},
    )

    mock_scholarship_discovery_client.search_scholarships.assert_not_awaited()
    mock_eligibility_service.evaluate.assert_not_awaited()
    assert result["source"] == "orchestrator"
    assert result.get("pending_intent") == "eligibility_check"


@pytest.mark.asyncio
async def test_handle_eligibility_check_clarification_reply_generic_program_reasks_details(
    chat_service,
    mock_eligibility_service,
    mock_program_discovery_client,
    mock_scholarship_discovery_client,
):
    """Generic replies like 'Master of Science' should trigger re-clarification, not forced evaluation."""
    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content="Master of Science",
        workflow_run_id="wf-generic-program-title",
        gate={"allowed": True},
        is_clarification_reply=True,
        pending_eligibility_context={"entity_type": "program"},
    )

    mock_program_discovery_client.search_programs.assert_not_awaited()
    mock_scholarship_discovery_client.search_scholarships.assert_not_awaited()
    mock_eligibility_service.evaluate.assert_not_awaited()
    assert result["source"] == "orchestrator"
    assert result.get("pending_intent") == "eligibility_check"
    assert "include the university" in result["answer"].lower()
    assert "program id" in result["answer"].lower()


@pytest.mark.asyncio
async def test_handle_eligibility_check_generic_program_followup_asks_for_university_context(
    chat_service,
    mock_eligibility_service,
    mock_program_discovery_client,
    mock_scholarship_discovery_client,
):
    """Second-turn generic replies should request university + full program title."""
    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content="Master of Science",
        workflow_run_id="wf-generic-followup",
        gate={"allowed": True},
        is_clarification_reply=True,
        pending_eligibility_context={"entity_type": "program"},
    )

    mock_program_discovery_client.search_programs.assert_not_awaited()
    mock_scholarship_discovery_client.search_scholarships.assert_not_awaited()
    mock_eligibility_service.evaluate.assert_not_awaited()
    assert result["source"] == "orchestrator"
    assert result.get("pending_intent") == "eligibility_check"
    assert "include the university" in result["answer"].lower()
    assert "full program name" in result["answer"].lower()


@pytest.mark.asyncio
async def test_handle_eligibility_check_institution_prefixed_generic_program_followup_reasks_details(
    chat_service,
    mock_eligibility_service,
    mock_program_discovery_client,
    mock_scholarship_discovery_client,
):
    """Replies like 'University of Sydney Master of Science' should still be treated as generic degree titles."""
    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content="University of Sydney Master of Science",
        workflow_run_id="wf-generic-followup-institution-prefixed",
        gate={"allowed": True},
        is_clarification_reply=True,
        pending_eligibility_context={"entity_type": "program"},
    )

    mock_program_discovery_client.search_programs.assert_not_awaited()
    mock_scholarship_discovery_client.search_scholarships.assert_not_awaited()
    mock_eligibility_service.evaluate.assert_not_awaited()
    assert result["source"] == "orchestrator"
    assert result.get("pending_intent") == "eligibility_check"
    assert "include the university" in result["answer"].lower()
    assert "full program name" in result["answer"].lower()


@pytest.mark.asyncio
async def test_handle_eligibility_check_specific_program_unmatched_after_clarification_returns_exact_match_guidance(
    chat_service,
    mock_eligibility_service,
    mock_program_discovery_client,
    mock_scholarship_discovery_client,
):
    """Specific unresolved replies should not fall back to the initial broad clarification prompt."""
    mock_program_discovery_client.search_programs.return_value = {"data": []}
    mock_program_discovery_client.search_institutions.return_value = {"data": []}

    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content="NUS Master of Science in Computer Science",
        workflow_run_id="wf-specific-unmatched-followup",
        gate={"allowed": True},
        is_clarification_reply=True,
        pending_eligibility_context={"entity_type": "program"},
    )

    mock_scholarship_discovery_client.search_scholarships.assert_not_awaited()
    mock_eligibility_service.evaluate.assert_not_awaited()
    assert result["source"] == "orchestrator"
    assert result.get("pending_intent") == "eligibility_check"
    assert "couldn't find an exact program match" in result["answer"].lower()
    assert "official program name" in result["answer"].lower()


@pytest.mark.asyncio
async def test_handle_eligibility_check_profile_dependency_error_returns_missing_fields_guidance(
    chat_service,
    mock_eligibility_service,
    mock_profile_gate_service,
):
    entity_id = "d4e5f6a7-0000-0000-0000-000000000004"
    mock_eligibility_service.evaluate.side_effect = HTTPException(
        status_code=424,
        detail="Student profile is required before eligibility can be evaluated.",
    )
    mock_profile_gate_service.evaluate_gate.return_value = {
        "user_id": "user-456",
        "allowed": False,
        "missing_required_fields": ["gpa", "gpa_scale"],
        "missing_fields": ["gpa", "gpa_scale"],
        "reason": "profile_incomplete_for_intent",
    }

    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content=f"Check my eligibility for program {entity_id}",
        workflow_run_id="wf-elig-profile-err",
        gate={"allowed": True},
    )

    assert result["source"] == "eligibility_engine"
    assert "profile is incomplete" in result["answer"].lower()
    assert "gpa" in result["answer"].lower()
    assert "gpa scale" in result["answer"].lower()


@pytest.mark.asyncio
async def test_handle_eligibility_check_entity_dependency_error_returns_entity_guidance(
    chat_service,
    mock_eligibility_service,
):
    entity_id = "e5f6a7b8-0000-0000-0000-000000000005"
    mock_eligibility_service.evaluate.side_effect = HTTPException(
        status_code=502,
        detail="Unable to fetch program details for eligibility evaluation.",
    )

    result = await chat_service._handle_eligibility_check(
        user_id="user-456",
        chat_id="chat-123",
        content=f"Check my eligibility for program {entity_id}",
        workflow_run_id="wf-elig-entity-err",
        gate={"allowed": True},
    )

    assert result["source"] == "eligibility_engine"
    assert "couldn't fetch the latest details" in result["answer"].lower()
    assert "exact name/id" in result["answer"].lower()


@pytest.mark.asyncio
async def test_send_message_eligibility_check_intent_calls_handler(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
    mock_eligibility_service,
):
    """eligibility_check intent routes to _handle_eligibility_check, not static message."""
    mock_profile_gate_service.evaluate_gate.return_value = {
        "user_id": "user-456",
        "completed": True,
        "missing_fields": [],
        "updated_at": None,
        "allowed": True,
        "reason": "profile_complete_for_intent",
    }
    chat_service.intent_registry_service.detect_intent.return_value = "eligibility_check"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "eligibility-engine"}
    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message

    entity_id = "c3d4e5f6-0000-0000-0000-000000000003"
    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content=f"Check my eligibility for program {entity_id}",
    )

    mock_eligibility_service.evaluate.assert_awaited_once()
    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert "78.5" in assistant_kwargs["content"]
    assert assistant_kwargs["metadata"]["intent"] == "eligibility_check"


def test_detect_entity_type_for_eligibility_program_default():
    assert ChatService._detect_entity_type_for_eligibility("Am I eligible for this program?") == "program"


def test_detect_entity_type_for_eligibility_scholarship_keyword():
    assert ChatService._detect_entity_type_for_eligibility("Do I qualify for this scholarship?") == "scholarship"


def test_detect_entity_type_for_eligibility_grant_keyword():
    assert ChatService._detect_entity_type_for_eligibility("Check eligibility for this grant") == "scholarship"


def test_format_eligibility_response_high_score():
    result = {
        "match_result": {
            "match_score": 85.0,
            "confidence_level": "high",
            "score_breakdown": {"gpa": 30, "research_alignment": 40, "language": 15},
        },
        "attribution_report": {"narrative": "Excellent profile alignment."},
        "agent_reasoning": {},
    }
    answer = ChatService._format_eligibility_response(result=result, entity_type="program", entity_name="MSc AI")
    assert "85.0" in answer
    assert "strong match" in answer.lower()
    assert "MSc AI" in answer
    assert "Excellent profile alignment" in answer


def test_format_eligibility_response_low_score():
    result = {
        "match_result": {
            "match_score": 25.0,
            "confidence_level": "low",
            "score_breakdown": {},
        },
        "attribution_report": {},
        "agent_reasoning": {},
    }
    answer = ChatService._format_eligibility_response(result=result, entity_type="program", entity_name=None)
    assert "25.0" in answer
    assert "below the typical threshold" in answer.lower()


def test_format_eligibility_response_missing_score():
    result = {"match_result": {}, "attribution_report": {}}
    answer = ChatService._format_eligibility_response(result=result, entity_type="program", entity_name="Test Program")
    assert "wasn't able to produce a score" in answer


def test_eligibility_clarification_message_program():
    msg = ChatService._eligibility_clarification_message("program")
    assert "program" in msg.lower()
    assert "name or ID" in msg


def test_eligibility_clarification_message_scholarship():
    msg = ChatService._eligibility_clarification_message("scholarship")
    assert "scholarship" in msg.lower()


def test_extract_program_institution_and_title_hint_simple_format():
    """Extract institution/title from standard pattern like 'NUS Master of Science'."""
    institution, title = ChatService._extract_program_institution_and_title_hint(
        "NUS Master of Science in Computer Science"
    )
    assert institution == "NUS"
    assert "Master" in title


# --- _maybe_override_intent_for_clarification_reply: eligibility pending_intent ---


def test_override_intent_eligibility_clarification_pending():
    """When assistant metadata has pending_intent=eligibility_check, override non-eligibility intent."""
    last_msg = {
        "metadata": {
            "pending_intent": "eligibility_check",
            "profile_gate": {"allowed": True, "reason": "gate_passed"},
        }
    }
    result = ChatService._maybe_override_intent_for_clarification_reply(
        "program_discovery", "NUS Master of Computing", last_msg
    )
    assert result == "eligibility_check"


def test_override_intent_eligibility_already_detected():
    """When detected intent is already eligibility_check, return as-is regardless of pending_intent."""
    last_msg = {
        "metadata": {
            "pending_intent": "eligibility_check",
            "profile_gate": {"allowed": True, "reason": "gate_passed"},
        }
    }
    result = ChatService._maybe_override_intent_for_clarification_reply(
        "eligibility_check", "NUS Master of Computing", last_msg
    )
    assert result == "eligibility_check"


def test_override_intent_no_pending_intent_falls_through():
    """When metadata has no pending_intent, profile-gate logic runs as before."""
    last_msg = {
        "metadata": {
            "profile_gate": {"allowed": True, "reason": "gate_passed"},
        }
    }
    result = ChatService._maybe_override_intent_for_clarification_reply(
        "program_discovery", "Master of Computing", last_msg
    )
    assert result == "program_discovery"


def test_override_intent_domain_pending_from_profile_completion_reply():
    """When pending_intent is a domain intent, profile-completion slot replies should continue it."""
    last_msg = {
        "metadata": {
            "pending_intent": "scholarship_search",
            "profile_gate": {"allowed": False, "reason": "profile_incomplete_for_intent"},
        }
    }
    result = ChatService._maybe_override_intent_for_clarification_reply("profile_completion", "Singapore", last_msg)
    assert result == "scholarship_search"


def test_override_intent_no_metadata_returns_detected():
    """When latest assistant message has no metadata, detected intent is unchanged."""
    result = ChatService._maybe_override_intent_for_clarification_reply(
        "program_discovery", "NUS Master of Computing", {"role": "assistant", "content": "Please specify."}
    )
    assert result == "program_discovery"


@pytest.mark.asyncio
async def test_send_message_gate_blocked_scholarship_sets_pending_intent_metadata(
    chat_service,
    mock_chat_repo,
    mock_message_repo,
    sample_chat,
    sample_message,
    mock_profile_gate_service,
):
    """Blocked scholarship turns should persist pending_intent for the next slot-answer turn."""
    chat_service.intent_registry_service.detect_intent.return_value = "scholarship_search"
    chat_service.intent_registry_service.get_policy.return_value = {"agent": "scholarship-discovery"}

    mock_profile_gate_service.evaluate_gate.side_effect = [
        {
            "user_id": "user-456",
            "profile_id": "profile-1",
            "completed": False,
            "missing_fields": ["target_study_country"],
            "missing_required_fields": ["target_study_country"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
        },
        {
            "user_id": "user-456",
            "profile_id": "profile-1",
            "completed": False,
            "missing_fields": ["target_study_country"],
            "missing_required_fields": ["target_study_country"],
            "updated_at": None,
            "allowed": False,
            "reason": "profile_incomplete_for_intent",
        },
    ]
    mock_profile_gate_service.collect_profile_updates_from_chat.return_value = {"applied_fields": ["funding_source"]}
    mock_profile_gate_service.get_profile_clarifications.return_value = {
        "profile_id": "profile-1",
        "status": "needs_clarification",
        "clarification_queue": [
            {
                "field": "target_study_country",
                "question": "Please share your preferred study country.",
            }
        ],
    }

    mock_chat_repo.get_by_id_with_user.return_value = sample_chat
    mock_chat_repo.get_by_id.return_value = {**sample_chat, "message_count": 2}
    mock_message_repo.create.return_value = sample_message
    mock_message_repo.list_by_chat.return_value = []

    await chat_service.send_message(
        user_id="user-456",
        chat_id="chat-123",
        content="what about scholarship for me",
    )

    _, assistant_kwargs = mock_message_repo.create.call_args_list[-1]
    assert assistant_kwargs["metadata"]["pending_intent"] == "scholarship_search"


def test_handle_eligibility_check_no_entity_includes_pending_intent(
    anyio_backend,
):
    """Clarification response dict must carry pending_intent=eligibility_check."""
    _ = anyio_backend

    async def _run():
        service = MagicMock()
        service._detect_entity_type_for_eligibility = MagicMock(return_value="program")
        service._resolve_entity_for_eligibility = AsyncMock(return_value=(None, None))
        service._eligibility_clarification_message = MagicMock(return_value="Please provide a program name.")

        result = await ChatService._handle_eligibility_check(
            service,
            user_id="u1",
            chat_id="c1",
            content="am I eligible",
            workflow_run_id="wf-1",
            gate={"allowed": True},
        )
        return result

    result = asyncio.get_event_loop().run_until_complete(_run())
    assert result.get("pending_intent") == "eligibility_check"
    assert result["source"] == "orchestrator"
