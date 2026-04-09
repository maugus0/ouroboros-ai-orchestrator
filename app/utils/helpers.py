"""Common utility functions."""

import uuid
from datetime import datetime, timezone

from app.utils.timezone import isoformat_z


def generate_uuid() -> str:
    """Generate a new UUID v4 string."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def get_current_time() -> str:
    """Return current UTC time as ISO 8601 string with trailing Z."""
    return isoformat_z(datetime.now(timezone.utc))
