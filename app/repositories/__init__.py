"""Repository layer for database access (raw SQL with aiomysql)."""

from app.repositories.user_repo import UserRepository

__all__ = [
    "UserRepository",
]
