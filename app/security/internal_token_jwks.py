"""Helpers to publish internal token signing keys as JWKS."""

from __future__ import annotations

import json
from typing import Any

from cryptography.hazmat.primitives import serialization
from jwt.algorithms import RSAAlgorithm

from app.config import settings

_RSA_SIGNING_ALGORITHMS = {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512"}


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
    signing_algorithm = str(settings.INTERNAL_TOKEN_SIGNING_ALGORITHM or "").upper()
    if signing_algorithm not in _RSA_SIGNING_ALGORITHMS:
        raise ValueError(
            "Internal JWKS requires an RSA signing algorithm (RS256, RS384, RS512, PS256, PS384, or PS512)"
        )

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

        try:
            public_key = _to_public_key_object(key_pem)
        except (TypeError, ValueError) as exc:
            raise ValueError("Internal JWKS requires RSA PEM key material for configured signing keys") from exc

        jwk = _to_jwk_dict(public_key)
        jwk.update(
            {
                "kid": kid,
                "use": "sig",
                "alg": signing_algorithm,
            }
        )
        jwk_keys.append(jwk)
        seen_kids.add(kid)

    return {"keys": jwk_keys}
