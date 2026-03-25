"""Data-access layer for the chats and messages tables."""

from app.core.database import get_pool
from app.core.logging import get_logger

logger = get_logger(__name__)


class ChatRepository:
    """CRUD operations on ``chats`` and ``messages`` tables."""

    # Implementation will be added when we build the chat feature.
    pass
