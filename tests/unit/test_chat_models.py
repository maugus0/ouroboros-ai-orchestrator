"""Unit tests for chat Pydantic models."""

import pytest
from pydantic import ValidationError

from app.models.chat import CreateChatRequest, SendMessageRequest, UpdateChatRequest

# ── SendMessageRequest Tests ─────────────────────────────────────────────────


def test_send_message_valid():
    """Test valid message request."""
    req = SendMessageRequest(content="Hello, world!")
    assert req.content == "Hello, world!"


def test_send_message_strips_whitespace():
    """Test that content whitespace is stripped."""
    req = SendMessageRequest(content="  Hello  ")
    assert req.content == "Hello"


def test_send_message_empty_fails():
    """Test that empty content fails validation."""
    with pytest.raises(ValidationError):
        SendMessageRequest(content="")


def test_send_message_whitespace_only_fails():
    """Test that whitespace-only content fails validation."""
    with pytest.raises(ValidationError):
        SendMessageRequest(content="   ")


def test_send_message_too_long_fails():
    """Test that content over 10000 chars fails."""
    with pytest.raises(ValidationError):
        SendMessageRequest(content="x" * 10001)


def test_send_message_exact_max_length():
    """Test that content at exactly 10000 chars passes."""
    req = SendMessageRequest(content="x" * 10000)
    assert len(req.content) == 10000


# ── UpdateChatRequest Tests ──────────────────────────────────────────────────


def test_update_chat_valid():
    """Test valid title update."""
    req = UpdateChatRequest(title="My Chat")
    assert req.title == "My Chat"


def test_update_chat_strips_whitespace():
    """Test that title whitespace is stripped."""
    req = UpdateChatRequest(title="  My Chat  ")
    assert req.title == "My Chat"


def test_update_chat_empty_fails():
    """Test that empty title fails validation."""
    with pytest.raises(ValidationError):
        UpdateChatRequest(title="")


def test_update_chat_whitespace_only_fails():
    """Test that whitespace-only title fails validation."""
    with pytest.raises(ValidationError):
        UpdateChatRequest(title="   ")


def test_update_chat_too_long_fails():
    """Test that title over 255 chars fails."""
    with pytest.raises(ValidationError):
        UpdateChatRequest(title="x" * 256)


def test_update_chat_exact_max_length():
    """Test that title at exactly 255 chars passes."""
    req = UpdateChatRequest(title="x" * 255)
    assert len(req.title) == 255


# ── CreateChatRequest Tests ──────────────────────────────────────────────────


def test_create_chat_empty():
    """Test creating chat without message."""
    req = CreateChatRequest()
    assert req.message is None


def test_create_chat_with_message():
    """Test creating chat with message."""
    req = CreateChatRequest(message="Hello!")
    assert req.message == "Hello!"


def test_create_chat_message_too_long_fails():
    """Test that message over 10000 chars fails."""
    with pytest.raises(ValidationError):
        CreateChatRequest(message="x" * 10001)


def test_create_chat_message_empty_string_coerces_to_none():
    """Test that empty string message is coerced to None."""
    req = CreateChatRequest(message="")
    assert req.message is None


def test_create_chat_message_whitespace_only_coerces_to_none():
    """Test that whitespace-only message is coerced to None."""
    req = CreateChatRequest(message="   ")
    assert req.message is None


def test_create_chat_message_strips_whitespace():
    """Test that message whitespace is stripped."""
    req = CreateChatRequest(message="  Hello  ")
    assert req.message == "Hello"


def test_create_chat_with_none_message():
    """Test that None message is allowed."""
    req = CreateChatRequest(message=None)
    assert req.message is None
