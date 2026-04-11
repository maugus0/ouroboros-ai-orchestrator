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
def chat_service(mock_chat_repo, mock_message_repo, mock_project_repo):
    """Create ChatService with mocked repositories."""
    return ChatService(
        chat_repo=mock_chat_repo,
        message_repo=mock_message_repo,
        project_repo=mock_project_repo,
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
async def test_create_chat_empty(chat_service, mock_chat_repo, sample_chat):
    """Test creating an empty chat without initial message."""
    mock_chat_repo.create.return_value = sample_chat

    result = await chat_service.create_chat(user_id="user-456", initial_message=None)

    assert result["id"] == "chat-123"
    assert result["user_id"] == "user-456"
    mock_chat_repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_create_chat_with_message(chat_service, mock_chat_repo, mock_message_repo, sample_chat, sample_message):
    """Test creating a chat with an initial message."""
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
async def test_send_message_success(chat_service, mock_chat_repo, mock_message_repo, sample_chat, sample_message):
    """Test sending a message successfully."""
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
