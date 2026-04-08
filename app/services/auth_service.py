"""Authentication business logic — signup, OTP, login, token lifecycle."""

import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException, status

from app.config import settings
from app.core.database import get_pool
from app.core.logging import get_logger
from app.repositories.auth_repo import AuthRepository
from app.repositories.user_repo import UserRepository
from app.services.twilio_service import TwilioService, get_twilio_service
from app.utils.jwt_util import JWTUtil
from app.utils.otp_util import can_request_new_otp, generate_otp, get_otp_expiry, is_otp_expired
from app.utils.password_util import hash_password, verify_password
from app.utils.phone_util import PhoneValidationError, mask_phone_number, validate_phone_number

logger = get_logger(__name__)


class AuthService:
    """Orchestrates the full authentication flow."""

    def __init__(
        self,
        user_repo: Optional[UserRepository] = None,
        auth_repo: Optional[AuthRepository] = None,
        jwt_util: Optional[JWTUtil] = None,
        twilio_service: Optional[TwilioService] = None,
    ) -> None:
        self._user_repo = user_repo
        self._auth_repo = auth_repo
        self.jwt_util = jwt_util or JWTUtil()
        self.twilio = twilio_service or get_twilio_service()

    @property
    def user_repo(self) -> UserRepository:
        if self._user_repo is None:
            self._user_repo = _lazy_user_repo()
        return self._user_repo

    @property
    def auth_repo(self) -> AuthRepository:
        if self._auth_repo is None:
            self._auth_repo = _lazy_auth_repo()
        return self._auth_repo

    # ── public API ───────────────────────────────────────────────

    async def signup(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        username: str,
        phone_number: str,
        password: str,
        first_name: str,
        last_name: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        e164, country = _parse_phone(phone_number)

        if await self.user_repo.phone_exists(e164):
            raise HTTPException(status.HTTP_409_CONFLICT, "Phone number already registered")
        if await self.user_repo.username_exists(username):
            raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")

        await self._check_otp_rate_limit(e164)

        user = await self.user_repo.create(
            username=username,
            phone_number=e164,
            phone_country_code=country,
            password_hash=hash_password(password),
            first_name=first_name,
            last_name=last_name,
        )

        otp = generate_otp()
        await self.user_repo.set_otp(user["id"], otp, get_otp_expiry())

        sms = await self.twilio.send_otp(e164, otp)
        if not sms.success:
            logger.error("otp_send_failed_signup", user_id=user["id"], error=sms.error_message)

        await self.auth_repo.log_otp_action(e164, "sent", ip_address, user_agent)

        logger.info("signup_complete", user_id=user["id"])
        return {
            "user_id": user["id"],
            "username": username,
            "phone_number": mask_phone_number(e164),
            "message": "OTP sent to your phone. Please verify to complete registration.",
        }

    async def verify_otp(
        self,
        phone_number: str,
        otp_code: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        e164, _ = _parse_phone(phone_number)
        user = await self._get_user_by_phone_or_404(e164)

        if user.get("phone_verified"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Phone already verified")
        if (user.get("otp_attempts") or 0) >= settings.OTP_MAX_ATTEMPTS:
            await self.auth_repo.log_otp_action(e164, "failed", ip_address, user_agent)
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts. Request a new OTP.")

        if is_otp_expired(user.get("otp_expires_at")):
            await self.auth_repo.log_otp_action(e164, "expired", ip_address, user_agent)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "OTP has expired. Please request a new one.")

        if not user.get("otp_code") or user["otp_code"] != otp_code:
            await self.user_repo.increment_otp_attempts(user["id"])
            await self.auth_repo.log_otp_action(e164, "failed", ip_address, user_agent)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid OTP code")

        await self.user_repo.verify_phone(user["id"])
        await self.auth_repo.log_otp_action(e164, "verified", ip_address, user_agent)

        tokens = await self._issue_tokens(user, user_agent, ip_address)
        await self.user_repo.update_last_login(user["id"])
        profile = await self.user_repo.get_by_id(user["id"])

        logger.info("otp_verified", user_id=user["id"])
        return {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "token_type": "Bearer",  # nosec B105
            "expires_in": self.jwt_util.access_ttl,
            "user": _sanitize(profile),
        }

    async def resend_otp(
        self,
        phone_number: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        e164, _ = _parse_phone(phone_number)
        user = await self._get_user_by_phone_or_404(e164)

        if user.get("phone_verified"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Phone already verified")

        allowed, wait = can_request_new_otp(user.get("otp_last_sent_at"))
        if not allowed:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Please wait {wait}s before requesting a new OTP")

        await self._check_otp_rate_limit(e164)

        otp = generate_otp()
        await self.user_repo.set_otp(user["id"], otp, get_otp_expiry())

        sms = await self.twilio.send_otp(e164, otp)
        if not sms.success:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to send OTP. Please try again.")

        await self.auth_repo.log_otp_action(e164, "sent", ip_address, user_agent)

        logger.info("otp_resent", user_id=user["id"])
        return {"message": "OTP sent to your phone", "phone_number": mask_phone_number(e164)}

    async def login(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        password: str,
        phone_number: Optional[str] = None,
        username: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        user = await self._resolve_user(phone_number, username)

        if not user or not verify_password(password, user.get("password_hash", "")):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
        if not user.get("is_active", True):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")
        if not user.get("phone_verified"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Phone not verified. Complete OTP verification first.")

        tokens = await self._issue_tokens(user, user_agent, ip_address)
        await self.user_repo.update_last_login(user["id"])
        profile = await self.user_repo.get_by_id(user["id"])

        logger.info("login_success", user_id=user["id"])
        return {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "token_type": "Bearer",  # nosec B105
            "expires_in": self.jwt_util.access_ttl,
            "user": _sanitize(profile),
            "profile_completed": profile.get("profile_completed", False),
        }

    async def refresh_tokens(  # pylint: disable=too-many-locals
        self,
        refresh_token: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        claims = self.jwt_util.validate_token(refresh_token)
        if not self.jwt_util.is_refresh_token(claims):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token required")

        sid = claims.get("sid")
        uid = claims.get("sub")
        jti = claims.get("jti")
        if not sid or not uid or not jti:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed refresh token")

        session = await self.auth_repo.get_session(sid)
        if not session:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session not found")
        if session.get("is_revoked"):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session revoked")

        exp = session.get("expires_at")
        if exp:
            now = datetime.now(timezone.utc)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if now > exp:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

        stored_hash = session.get("token_hash", "")
        if _sha256(jti) != stored_hash:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

        user = await self.user_repo.get_by_id(uid)
        if not user or not user.get("is_active", True):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or disabled")

        new_jti = secrets.token_urlsafe(64)
        new_hash = _sha256(new_jti)
        await self.auth_repo.update_session_token(sid, new_hash, self.jwt_util.refresh_ttl, user_agent, ip_address)

        access = self.jwt_util.generate_access_token(
            user_id=uid, username=user.get("username"), phone_number=user.get("phone_number"), session_id=sid
        )
        refresh = self.jwt_util.generate_refresh_token(user_id=uid, session_id=sid, token_id=new_jti)

        await self.user_repo.update_last_active(uid)
        logger.info("tokens_refreshed", user_id=uid, session_id=sid)
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "Bearer",  # nosec B105
            "expires_in": self.jwt_util.access_ttl,
        }

    async def logout(self, access_token: str) -> Dict[str, str]:
        claims = self.jwt_util.validate_token(access_token)
        if not self.jwt_util.is_access_token(claims):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Access token required")

        sid = claims.get("sid")
        if sid:
            await self.auth_repo.revoke_session(sid)
        logger.info("logout", user_id=claims.get("sub"), session_id=sid)
        return {"message": "Logged out successfully"}

    async def get_profile(self, user_id: str) -> Dict[str, Any]:
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        await self.user_repo.update_last_active(user_id)
        return _sanitize(user)

    async def update_profile(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        user_id: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        email: Optional[str] = None,
        about_me: Optional[str] = None,
        profession: Optional[str] = None,
        interest: Optional[str] = None,
    ) -> Dict[str, Any]:
        user = await self.user_repo.update_profile(
            user_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            about_me=about_me,
            profession=profession,
            interest=interest,
        )
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        return _sanitize(user)

    async def get_profile_status(self, user_id: str) -> Dict[str, Any]:
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        return {
            "profile_completed": user.get("profile_completed", False),
            "phone_verified": user.get("phone_verified", False),
        }

    async def get_sessions(self, user_id: str, active_only: bool = True) -> list:
        return await self.auth_repo.get_user_sessions(user_id, active_only=active_only)

    # ── private helpers ──────────────────────────────────────────

    async def _resolve_user(self, phone_number: Optional[str], username: Optional[str]) -> Optional[Dict[str, Any]]:
        """Look up user by phone number or username."""
        if phone_number:
            e164, _ = _parse_phone(phone_number)
            return await self.user_repo.get_by_phone(e164)
        if username:
            return await self.user_repo.get_by_username(username.lower())
        return None

    async def _issue_tokens(
        self, user: Dict[str, Any], user_agent: Optional[str], ip_address: Optional[str]
    ) -> Dict[str, str]:
        sid = str(uuid.uuid4())
        jti = secrets.token_urlsafe(64)
        token_hash = _sha256(jti)

        await self.auth_repo.create_session(
            session_id=sid,
            user_id=user["id"],
            token_hash=token_hash,
            ttl_seconds=self.jwt_util.refresh_ttl,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        access = self.jwt_util.generate_access_token(
            user_id=user["id"],
            username=user.get("username"),
            phone_number=user.get("phone_number"),
            session_id=sid,
        )
        refresh = self.jwt_util.generate_refresh_token(user_id=user["id"], session_id=sid, token_id=jti)
        return {"access_token": access, "refresh_token": refresh}

    async def _get_user_by_phone_or_404(self, e164: str) -> Dict[str, Any]:
        user = await self.user_repo.get_by_phone(e164)
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        return user

    async def _check_otp_rate_limit(self, e164: str) -> None:
        count = await self.user_repo.get_otp_send_count(e164, settings.OTP_RATE_LIMIT_WINDOW_SECONDS)
        if count >= settings.OTP_RATE_LIMIT_MAX_REQUESTS:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many OTP requests. Please try again later.")


# ── module-level helpers ─────────────────────────────────────────


def _sha256(value: str) -> str:
    """Hex-digest SHA-256 hash (used for high-entropy refresh token JTIs)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _parse_phone(raw: str):
    try:
        return validate_phone_number(raw)
    except PhoneValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _sanitize(user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not user:
        return {}
    exclude = {"password_hash", "otp_code", "otp_expires_at", "otp_attempts", "otp_last_sent_at"}
    return {k: v for k, v in user.items() if k not in exclude}


def _lazy_user_repo() -> UserRepository:
    return UserRepository(get_pool())


def _lazy_auth_repo() -> AuthRepository:
    return AuthRepository(get_pool())
