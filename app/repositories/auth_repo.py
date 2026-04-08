"""Data-access layer for auth sessions and OTP audit logs."""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiomysql

from app.core.logging import get_logger

logger = get_logger(__name__)


class AuthRepository:
    """CRUD on ``auth_sessions`` and ``otp_logs`` tables."""

    def __init__(self, pool: aiomysql.Pool) -> None:
        self.pool = pool

    # ── session lifecycle ─────────────────────────────────────────

    async def create_session(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        session_id: str,
        user_id: str,
        token_hash: str,
        ttl_seconds: int,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> dict[str, Any]:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        query = """
            INSERT INTO auth_sessions
                (id, user_id, token_hash, expires_at, last_active_at, user_agent, ip_address)
            VALUES (%s, %s, %s, %s, UTC_TIMESTAMP(), %s, %s)
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (session_id, user_id, token_hash, expires_at, user_agent, ip_address))
                await conn.commit()
        logger.info("session_created", session_id=session_id, user_id=user_id)
        return {"session_id": session_id, "expires_at": expires_at}

    async def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        query = """
            SELECT id, user_id, token_hash, expires_at, is_revoked, revoked_at,
                   last_active_at, user_agent, ip_address, created_at, updated_at
            FROM auth_sessions WHERE id = %s
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (session_id,))
                row = await cur.fetchone()
                return dict(row) if row else None

    async def update_session_token(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        session_id: str,
        new_token_hash: str,
        ttl_seconds: int,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        query = """
            UPDATE auth_sessions
            SET token_hash = %s, expires_at = %s, last_active_at = UTC_TIMESTAMP(),
                user_agent = %s, ip_address = %s, updated_at = UTC_TIMESTAMP()
            WHERE id = %s AND is_revoked = FALSE
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (new_token_hash, expires_at, user_agent, ip_address, session_id))
                await conn.commit()
        logger.info("session_rotated", session_id=session_id)

    async def revoke_session(self, session_id: str) -> None:
        query = """
            UPDATE auth_sessions
            SET is_revoked = TRUE, revoked_at = UTC_TIMESTAMP(), updated_at = UTC_TIMESTAMP()
            WHERE id = %s
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (session_id,))
                await conn.commit()
        logger.info("session_revoked", session_id=session_id)

    async def revoke_all_user_sessions(self, user_id: str) -> int:
        query = """
            UPDATE auth_sessions
            SET is_revoked = TRUE, revoked_at = UTC_TIMESTAMP(), updated_at = UTC_TIMESTAMP()
            WHERE user_id = %s AND is_revoked = FALSE
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (user_id,))
                await conn.commit()
                count = cur.rowcount
        logger.info("all_sessions_revoked", user_id=user_id, count=count)
        return count

    async def get_user_sessions(self, user_id: str, active_only: bool = True) -> list[dict[str, Any]]:
        """List sessions for a user. Includes session duration data."""
        if active_only:
            query = """
                SELECT id, user_agent, ip_address, created_at, last_active_at, expires_at
                FROM auth_sessions
                WHERE user_id = %s AND is_revoked = FALSE AND expires_at > UTC_TIMESTAMP()
                ORDER BY created_at DESC
            """
        else:
            query = """
                SELECT id, user_agent, ip_address, is_revoked, revoked_at,
                       created_at, last_active_at, expires_at
                FROM auth_sessions
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 50
            """
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (user_id,))
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    async def cleanup_expired(self) -> int:
        query = "DELETE FROM auth_sessions WHERE expires_at < UTC_TIMESTAMP() AND is_revoked = TRUE"
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query)
                await conn.commit()
                return cur.rowcount

    # ── OTP audit log ────────────────────────────────────────────

    async def log_otp_action(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        phone_number: str,
        action: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        delivery_status: Optional[str] = None,
        twilio_message_sid: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Log an OTP lifecycle event with optional Twilio delivery details."""
        query = """
            INSERT INTO otp_logs
                (phone_number, action, delivery_status, twilio_message_sid,
                 error_message, ip_address, user_agent)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (phone_number, action, delivery_status, twilio_message_sid, error_message, ip_address, user_agent),
                )
                await conn.commit()
