"""Data-access layer for the users table (raw SQL, aiomysql)."""

from app.core.logging import get_logger

logger = get_logger(__name__)


class UserRepository:
    """CRUD operations on the ``users`` table."""

    # Implementation will be added when we build the auth feature.
    pass
