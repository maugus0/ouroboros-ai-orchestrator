"""Internal short-lived token issuer for orchestrator service-to-service calls."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

import jwt

from app.config import settings


class InternalTokenIssuer:
    """Issue audience-bound internal tokens for downstream services."""

    def __init__(
        self,
        *,
        enabled: Optional[bool] = None,
        issuer: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        signing_algorithm: Optional[str] = None,
        private_key: Optional[str] = None,
        active_kid: Optional[str] = None,
        audience_map: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.enabled = settings.INTERNAL_TOKEN_ENABLED if enabled is None else bool(enabled)
        self.issuer = settings.INTERNAL_TOKEN_ISSUER if issuer is None else str(issuer)
        self.ttl_seconds = int(settings.INTERNAL_TOKEN_TTL_SECONDS if ttl_seconds is None else ttl_seconds)
        self.signing_algorithm = (
            settings.INTERNAL_TOKEN_SIGNING_ALGORITHM if signing_algorithm is None else str(signing_algorithm)
        )
        key_value = settings.INTERNAL_TOKEN_PRIVATE_KEY if private_key is None else str(private_key)
        self.private_key = self._normalize_key(key_value)
        self.active_kid = settings.INTERNAL_TOKEN_ACTIVE_KID if active_kid is None else str(active_kid)
        if audience_map is None:
            self.audience_map = settings.get_internal_token_audience_map()
        else:
            self.audience_map = {str(key): str(value) for key, value in dict(audience_map).items()}

    @staticmethod
    def _normalize_key(raw_value: str) -> str:
        if not raw_value:
            return ""
        value = raw_value.strip()
        if "\\n" in value:
            value = value.replace("\\n", "\n")
        return value

    def resolve_audience(self, service_name: str) -> str:
        return self.audience_map.get(service_name, service_name)

    def issue_service_token(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        *,
        sub: str,
        aud: str,
        sid: Optional[str] = None,
        trace_id: Optional[str] = None,
        extra_claims: Optional[dict[str, Any]] = None,
    ) -> str:
        if not self.enabled:
            raise RuntimeError("internal token issuer disabled")
        if not self.private_key:
            raise RuntimeError("internal token private key not configured")

        now = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "sub": sub,
            "aud": aud,
            "iss": self.issuer,
            "iat": now,
            "exp": now + timedelta(seconds=self.ttl_seconds),
            "trace_id": trace_id or str(uuid.uuid4()),
            "jti": str(uuid.uuid4()),
        }
        if sid:
            payload["sid"] = sid
        if extra_claims:
            payload.update(extra_claims)

        headers: dict[str, Any] = {}
        if self.active_kid:
            headers["kid"] = self.active_kid

        return jwt.encode(payload, self.private_key, algorithm=self.signing_algorithm, headers=headers)

    def build_bearer_token(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        *,
        sub: str,
        aud: str,
        sid: Optional[str] = None,
        trace_id: Optional[str] = None,
        extra_claims: Optional[dict[str, Any]] = None,
    ) -> str:
        token = self.issue_service_token(
            sub=sub,
            aud=aud,
            sid=sid,
            trace_id=trace_id,
            extra_claims=extra_claims,
        )
        return f"Bearer {token}"
