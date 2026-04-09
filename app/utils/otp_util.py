"""OTP generation and expiry utilities."""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Tuple

from app.config import settings


def generate_otp(length: int | None = None) -> str:
    """Return a cryptographically-secure numeric OTP."""
    n = length or settings.OTP_LENGTH
    return "".join(secrets.choice("0123456789") for _ in range(n))


def get_otp_expiry() -> datetime:
    """Return a UTC datetime ``OTP_EXPIRY_SECONDS`` from now."""
    return datetime.now(timezone.utc) + timedelta(seconds=settings.OTP_EXPIRY_SECONDS)


def is_otp_expired(expires_at: datetime | None) -> bool:
    """True when the OTP is past its expiry (or ``expires_at`` is None)."""
    if expires_at is None:
        return True
    now = datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return now > expires_at


def can_request_new_otp(last_sent_at: datetime | None) -> Tuple[bool, int]:
    """Check cooldown since the last OTP send.

    Returns:
        (allowed, seconds_remaining)
    """
    if last_sent_at is None:
        return True, 0

    now = datetime.now(timezone.utc)
    if last_sent_at.tzinfo is None:
        last_sent_at = last_sent_at.replace(tzinfo=timezone.utc)

    elapsed = (now - last_sent_at).total_seconds()
    cooldown = settings.OTP_COOLDOWN_SECONDS

    if elapsed >= cooldown:
        return True, 0
    return False, int(cooldown - elapsed)
