"""JSON response that serializes datetimes as UTC ISO 8601 with Z."""

import json
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any

from starlette.responses import JSONResponse

from app.utils.timezone import isoformat_z


def _json_default(value: Any) -> Any:
    """Default JSON serializer that normalizes datetimes to UTC Z."""
    if isinstance(value, datetime):
        return isoformat_z(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    return json.JSONEncoder().default(value)


class UTCJSONResponse(JSONResponse):
    """JSONResponse that renders datetimes as UTC ISO 8601 with trailing Z."""

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            default=_json_default,
        ).encode("utf-8")
