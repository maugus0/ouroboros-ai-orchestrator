"""Data-access layer for the users table (phone-based auth)."""

import uuid
from datetime import datetime
from typing import Any, Optional

import aiomysql
import pymysql.err  # type: ignore[import-untyped]

from app.core.logging import get_logger
from app.utils.profile_completion import is_profile_complete

logger = get_logger(__name__)


class DuplicateFieldError(Exception):
    """Raised when a unique field value already exists in the database."""

    def __init__(self, field: str, value: str) -> None:
        self.field = field
        self.value = value
        super().__init__(f"{field} '{value}' is already in use")


_PROFILE_COLS = """
    id, username, phone_number, phone_country_code, phone_verified,
    first_name, last_name, gender, email, about_me, profession, interest,
    profile_completed, mfa_enabled, password_changed_at,
    is_active, last_login, last_active, created_at, updated_at
"""

_AUTH_COLS = """
    id, username, phone_number, phone_country_code, phone_verified,
    password_hash, first_name, last_name, gender, email, about_me,
    profession, interest, profile_completed, mfa_enabled, password_changed_at,
    is_active, otp_code, otp_expires_at, otp_attempts, otp_last_sent_at,
    last_login, last_active, created_at, updated_at
"""


class UserRepository:
    """CRUD operations on the ``users`` table for phone-based authentication."""

    def __init__(self, pool: aiomysql.Pool) -> None:
        self.pool = pool

    # ── reads ────────────────────────────────────────────────────

    async def get_by_id(self, user_id: str) -> Optional[dict[str, Any]]:
        """Safe profile read (excludes password_hash & OTP fields)."""
        query = f"SELECT {_PROFILE_COLS} FROM users WHERE id = %s"  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (user_id,))
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_by_phone(self, phone_number: str) -> Optional[dict[str, Any]]:
        """Full row including password_hash and OTP fields (for auth logic)."""
        query = f"SELECT {_AUTH_COLS} FROM users WHERE phone_number = %s"  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (phone_number,))
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_by_username(self, username: str) -> Optional[dict[str, Any]]:
        """Full row including password_hash (case-insensitive username match)."""
        query = f"SELECT {_AUTH_COLS} FROM users WHERE LOWER(username) = LOWER(%s)"  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (username,))
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_by_id_with_otp(self, user_id: str) -> Optional[dict[str, Any]]:
        """Full row including OTP fields (for MFA verification)."""
        query = f"SELECT {_AUTH_COLS} FROM users WHERE id = %s"  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (user_id,))
                row = await cur.fetchone()
                return dict(row) if row else None

    async def phone_exists(self, phone_number: str) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1 FROM users WHERE phone_number = %s LIMIT 1", (phone_number,))
                return await cur.fetchone() is not None

    async def username_exists(self, username: str) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT 1 FROM users WHERE LOWER(username) = LOWER(%s) LIMIT 1",
                    (username,),
                )
                return await cur.fetchone() is not None

    async def email_exists(self, email: str, exclude_user_id: Optional[str] = None) -> bool:
        """Check if email is already in use (optionally excluding a specific user)."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                if exclude_user_id:
                    await cur.execute(
                        "SELECT 1 FROM users WHERE LOWER(email) = LOWER(%s) AND id != %s LIMIT 1",
                        (email, exclude_user_id),
                    )
                else:
                    await cur.execute(
                        "SELECT 1 FROM users WHERE LOWER(email) = LOWER(%s) LIMIT 1",
                        (email,),
                    )
                return await cur.fetchone() is not None

    # ── writes ───────────────────────────────────────────────────

    async def create(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        username: str,
        phone_number: str,
        phone_country_code: str,
        password_hash: str,
        first_name: str,
        last_name: str,
    ) -> dict[str, Any]:
        user_id = str(uuid.uuid4())
        query = """
            INSERT INTO users
                (id, username, phone_number, phone_country_code, password_hash,
                 first_name, last_name, phone_verified, profile_completed, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, FALSE, TRUE)
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (user_id, username, phone_number, phone_country_code, password_hash, first_name, last_name),
                )
                await conn.commit()

        logger.info("user_created", user_id=user_id, username=username)
        return await self.get_by_id(user_id)

    async def set_otp(self, user_id: str, otp_code: str, expires_at: datetime) -> None:
        query = """
            UPDATE users
            SET otp_code = %s, otp_expires_at = %s, otp_last_sent_at = UTC_TIMESTAMP(),
                otp_attempts = 0, updated_at = UTC_TIMESTAMP()
            WHERE id = %s
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (otp_code, expires_at, user_id))
                await conn.commit()

    async def increment_otp_attempts(self, user_id: str) -> None:
        query = "UPDATE users SET otp_attempts = otp_attempts + 1, updated_at = UTC_TIMESTAMP() WHERE id = %s"
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (user_id,))
                await conn.commit()

    async def clear_otp(self, user_id: str) -> None:
        """Clear transient OTP columns (after successful MFA verification)."""
        query = """
            UPDATE users
            SET otp_code = NULL, otp_expires_at = NULL,
                otp_attempts = 0, updated_at = UTC_TIMESTAMP()
            WHERE id = %s
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (user_id,))
                await conn.commit()

    async def verify_phone(self, user_id: str) -> None:
        """Mark phone as verified and clear transient OTP columns."""
        query = """
            UPDATE users
            SET phone_verified = TRUE, otp_code = NULL, otp_expires_at = NULL,
                otp_attempts = 0, updated_at = UTC_TIMESTAMP()
            WHERE id = %s
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (user_id,))
                await conn.commit()
        logger.info("phone_verified", user_id=user_id)

    async def update_last_login(self, user_id: str) -> None:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE users SET last_login = UTC_TIMESTAMP() WHERE id = %s", (user_id,))
                await conn.commit()

    async def update_last_active(self, user_id: str) -> None:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE users SET last_active = UTC_TIMESTAMP() WHERE id = %s", (user_id,))
                await conn.commit()

    async def update_profile(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        self,
        user_id: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        gender: Optional[str] = None,
        email: Optional[str] = None,
        about_me: Optional[str] = None,
        profession: Optional[str] = None,
        interest: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        sets: list[str] = []
        params: list[Any] = []

        for col, val in [
            ("first_name", first_name),
            ("last_name", last_name),
            ("gender", gender),
            ("email", email),
            ("about_me", about_me),
            ("profession", profession),
            ("interest", interest),
        ]:
            if val is not None:
                sets.append(f"{col} = %s")
                params.append(val)

        if not sets:
            return await self.get_by_id(user_id)

        sets.append("updated_at = UTC_TIMESTAMP()")
        params.append(user_id)

        # SET clauses are whitelisted fragments; user values are parameterized.
        query = "UPDATE users SET " + ", ".join(sets) + " WHERE id = %s"  # nosec B608
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, tuple(params))
                    await conn.commit()
        except pymysql.err.IntegrityError as exc:
            # MySQL error 1062 = duplicate entry
            error_msg = str(exc)
            if "Duplicate entry" in error_msg:
                if "email" in error_msg.lower():
                    raise DuplicateFieldError("email", email or "") from exc
                if "username" in error_msg.lower():
                    raise DuplicateFieldError("username", "") from exc
            raise

        row = await self.get_by_id(user_id)
        if row is None:
            return None
        complete = is_profile_complete(row)
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE users SET profile_completed = %s, updated_at = UTC_TIMESTAMP() WHERE id = %s",
                    (complete, user_id),
                )
                await conn.commit()

        logger.info("profile_updated", user_id=user_id, profile_completed=complete)
        return await self.get_by_id(user_id)

    async def set_mfa_enabled(self, user_id: str, enabled: bool) -> Optional[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE users SET mfa_enabled = %s, updated_at = UTC_TIMESTAMP() WHERE id = %s",
                    (enabled, user_id),
                )
                await conn.commit()
        logger.info("mfa_toggled", user_id=user_id, mfa_enabled=enabled)
        return await self.get_by_id(user_id)

    async def update_password(self, user_id: str, password_hash: str) -> None:
        """Set new password hash and stamp password_changed_at."""
        query = """
            UPDATE users
            SET password_hash = %s, password_changed_at = UTC_TIMESTAMP(),
                updated_at = UTC_TIMESTAMP()
            WHERE id = %s
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (password_hash, user_id))
                await conn.commit()
        logger.info("password_updated", user_id=user_id)

    async def soft_delete(self, user_id: str) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE users SET is_active = FALSE WHERE id = %s", (user_id,))
                await conn.commit()
                return cur.rowcount > 0

    # ── OTP rate-limit helper ────────────────────────────────────

    async def get_otp_send_count(self, phone_number: str, window_seconds: int) -> int:
        """Count 'sent' OTP log entries in the given window."""
        query = """
            SELECT COUNT(*) AS cnt FROM otp_logs
            WHERE phone_number = %s AND action = 'sent'
              AND created_at > DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s SECOND)
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (phone_number, window_seconds))
                row = await cur.fetchone()
                return row["cnt"] if row else 0
