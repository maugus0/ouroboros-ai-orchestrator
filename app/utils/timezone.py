"""Timezone helpers: UTC normalization and ISO serialization."""

from datetime import datetime, timezone
from typing import Any, Optional

UTC = timezone.utc


def ensure_utc(value: datetime) -> datetime:
    """Coerce datetimes to UTC; naive values are assumed to already be UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def isoformat_z(value: datetime) -> str:
    """Format datetime as ISO 8601 with a trailing Z."""
    return ensure_utc(value).isoformat().replace("+00:00", "Z")


def coerce_datetime(value: Any) -> Optional[datetime]:
    """Convert a datetime-like value to UTC-aware datetime if possible."""
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except (ValueError, TypeError):
            return None
    return None
