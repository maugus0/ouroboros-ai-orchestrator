"""Data-access layer for the users table (raw SQL, aiomysql)."""

import uuid
from datetime import datetime
from typing import Any

import aiomysql

from app.core.logging import get_logger

logger = get_logger(__name__)


class UserRepository:
    """
    CRUD operations on the ``users`` table.

    Supports both Auth0 users (via auth0_sub) and legacy users (password_hash).
    All methods return dictionaries for Pydantic compatibility.
    """

    def __init__(self, pool: aiomysql.Pool):
        self.pool = pool

    async def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        """Get user by internal UUID (primary key)."""
        query = """
            SELECT id, auth0_sub, auth_provider, name, email, is_active,
                   last_login, created_at, updated_at
            FROM users
            WHERE id = %s AND is_active = TRUE
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (user_id,))
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_by_auth0_sub(self, auth0_sub: str) -> dict[str, Any] | None:
        """
        Get user by Auth0 subject identifier.

        This is the primary lookup method for Auth0-authenticated users.
        The auth0_sub is unique per user in Auth0 (e.g., 'auth0|abc123').
        """
        query = """
            SELECT id, auth0_sub, auth_provider, name, email, is_active,
                   last_login, created_at, updated_at
            FROM users
            WHERE auth0_sub = %s AND is_active = TRUE
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (auth0_sub,))
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        """Get user by email address."""
        query = """
            SELECT id, auth0_sub, auth_provider, name, email, is_active,
                   last_login, created_at, updated_at
            FROM users
            WHERE email = %s AND is_active = TRUE
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (email,))
                row = await cur.fetchone()
                return dict(row) if row else None

    async def create_from_auth0(
        self,
        auth0_sub: str,
        email: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new user from Auth0 token claims (JIT provisioning).

        Called when a user authenticates via Auth0 for the first time.
        Creates a local user record with a new UUID that becomes the
        primary key for all FK relationships (chats, workflows, etc.).

        Args:
            auth0_sub: Auth0 subject identifier (e.g., 'auth0|abc123')
            email: User's email from Auth0 token
            name: User's name from Auth0 token (optional)

        Returns:
            The newly created user record as a dictionary
        """
        user_id = str(uuid.uuid4())
        display_name = name or email.split("@")[0]

        query = """
            INSERT INTO users (id, auth0_sub, auth_provider, name, email, password_hash)
            VALUES (%s, %s, 'auth0', %s, %s, NULL)
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (user_id, auth0_sub, display_name, email))
                await conn.commit()

        logger.info(
            "user_created_from_auth0",
            user_id=user_id,
            auth0_sub=auth0_sub,
            email=email,
        )
        return await self.get_by_id(user_id)

    async def update_last_login(self, user_id: str) -> None:
        """Update the last_login timestamp for a user."""
        query = "UPDATE users SET last_login = %s WHERE id = %s"
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (datetime.utcnow(), user_id))
                await conn.commit()

    async def update_profile(
        self,
        user_id: str,
        name: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any] | None:
        """Update user profile fields."""
        updates = []
        params = []

        if name is not None:
            updates.append("name = %s")
            params.append(name)
        if email is not None:
            updates.append("email = %s")
            params.append(email)

        if not updates:
            return await self.get_by_id(user_id)

        params.append(user_id)
        query = f"UPDATE users SET {', '.join(updates)} WHERE id = %s"

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, tuple(params))
                await conn.commit()

        return await self.get_by_id(user_id)

    async def soft_delete(self, user_id: str) -> bool:
        """Soft-delete a user by setting is_active = FALSE."""
        query = "UPDATE users SET is_active = FALSE WHERE id = %s"
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (user_id,))
                await conn.commit()
                return cur.rowcount > 0

    async def link_auth0_sub(self, user_id: str, auth0_sub: str) -> dict[str, Any] | None:
        """
        Link an existing user to an Auth0 account.

        Useful for migrating legacy users to Auth0.
        """
        query = """
            UPDATE users
            SET auth0_sub = %s, auth_provider = 'auth0'
            WHERE id = %s AND auth0_sub IS NULL
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (auth0_sub, user_id))
                await conn.commit()

        return await self.get_by_id(user_id)
