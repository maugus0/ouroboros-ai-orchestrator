"""Helpers to publish internal token signing keys as JWKS."""

from __future__ import annotations

import json
from typing import Any

from cryptography.hazmat.primitives import serialization
from jwt.algorithms import RSAAlgorithm

from app.config import settings


def _normalize_key(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if "\\n" in value:
        value = value.replace("\\n", "\n")
    return value


def _to_public_key_object(pem_value: str):
    pem_bytes = _normalize_key(pem_value).encode("utf-8")

    try:
        private_key = serialization.load_pem_private_key(pem_bytes, password=None)
        return private_key.public_key()
    except ValueError:
        return serialization.load_pem_public_key(pem_bytes)


def _to_jwk_dict(public_key: Any) -> dict[str, Any]:
    return json.loads(RSAAlgorithm.to_jwk(public_key))


def build_internal_token_jwks() -> dict[str, list[dict[str, Any]]]:
    """Build JWKS for active + overlapping verification keys."""
    key_entries: list[tuple[str, str]] = []

    if settings.INTERNAL_TOKEN_PRIVATE_KEY:
        key_entries.append((settings.INTERNAL_TOKEN_ACTIVE_KID, settings.INTERNAL_TOKEN_PRIVATE_KEY))

    for kid, key_pem in settings.get_internal_token_public_keys().items():
        key_entries.append((kid, key_pem))

    seen_kids: set[str] = set()
    jwk_keys: list[dict[str, Any]] = []

    for kid, key_pem in key_entries:
        if not kid or kid in seen_kids:
            continue
        if not key_pem:
            continue

        public_key = _to_public_key_object(key_pem)
        jwk = _to_jwk_dict(public_key)
        jwk.update(
            {
                "kid": kid,
                "use": "sig",
                "alg": settings.INTERNAL_TOKEN_SIGNING_ALGORITHM,
            }
        )
        jwk_keys.append(jwk)
        seen_kids.add(kid)

    return {"keys": jwk_keys}
