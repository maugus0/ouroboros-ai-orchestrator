"""Tests for internal JWKS publication."""

import json

from fastapi.testclient import TestClient

from app.main import app
from app.security.internal_token_jwks import build_internal_token_jwks

TEST_PUBLIC_KEY = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBAK96Mwd4Sjo88hdwpv87I0l2OnN0bg7f\n"
    "xnTKY95+zpj6tM99Cb6xgk6A6J6zV4PlMzy9hwwxRofD6Vxg9fIEd0MCAwEAAQ==\n"
    "-----END PUBLIC KEY-----"
)

TEST_INTERNAL_JWKS_JSON = json.dumps(
    {
        "internal-v1": TEST_PUBLIC_KEY,
        "internal-v2": TEST_PUBLIC_KEY,
    }
)


def _stub_internal_jwks_payload():
    return {
        "keys": [
            {
                "kty": "RSA",
                "n": "abc",
                "e": "AQAB",
                "kid": "internal-v1",
                "alg": "RS256",
                "use": "sig",
            }
        ]
    }


def _empty_jwks_payload():
    return {"keys": []}


def test_build_internal_jwks_includes_configured_overlapping_keys(monkeypatch):
    monkeypatch.setattr("app.security.internal_token_jwks.settings.INTERNAL_TOKEN_PRIVATE_KEY", "")
    monkeypatch.setattr("app.security.internal_token_jwks.settings.INTERNAL_TOKEN_SIGNING_ALGORITHM", "RS256")
    monkeypatch.setattr(
        "app.security.internal_token_jwks.settings.INTERNAL_TOKEN_PUBLIC_KEYS",
        TEST_INTERNAL_JWKS_JSON,
    )

    jwks = build_internal_token_jwks()

    assert len(jwks["keys"]) == 2
    kids = {entry["kid"] for entry in jwks["keys"]}
    assert kids == {"internal-v1", "internal-v2"}
    for entry in jwks["keys"]:
        assert entry["kty"] == "RSA"
        assert entry["use"] == "sig"
        assert entry["alg"] == "RS256"


def test_build_internal_jwks_rejects_non_rsa_algorithms(monkeypatch):
    monkeypatch.setattr("app.security.internal_token_jwks.settings.INTERNAL_TOKEN_PRIVATE_KEY", "")
    monkeypatch.setattr("app.security.internal_token_jwks.settings.INTERNAL_TOKEN_SIGNING_ALGORITHM", "HS256")
    monkeypatch.setattr(
        "app.security.internal_token_jwks.settings.INTERNAL_TOKEN_PUBLIC_KEYS",
        TEST_INTERNAL_JWKS_JSON,
    )

    try:
        build_internal_token_jwks()
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "RSA signing algorithm" in str(exc)


def test_internal_jwks_endpoint_returns_cacheable_payload(monkeypatch):
    monkeypatch.setattr("app.api.internal.settings.INTERNAL_TOKEN_JWKS_CACHE_MAX_AGE_SECONDS", 90)
    monkeypatch.setattr(
        "app.api.internal.build_internal_token_jwks",
        _stub_internal_jwks_payload,
    )

    with TestClient(app) as client:
        response = client.get("/internal/.well-known/jwks.json")

    assert response.status_code == 200
    assert response.headers.get("cache-control") == "public, max-age=90"
    body = response.json()
    assert body["keys"][0]["kid"] == "internal-v1"


def test_internal_jwks_endpoint_returns_503_when_unconfigured(monkeypatch):
    monkeypatch.setattr("app.api.internal.build_internal_token_jwks", _empty_jwks_payload)

    with TestClient(app) as client:
        response = client.get("/internal/.well-known/jwks.json")

    assert response.status_code == 503


def test_internal_jwks_endpoint_returns_503_for_non_rsa_algorithms(monkeypatch):
    monkeypatch.setattr("app.api.internal.settings.INTERNAL_TOKEN_SIGNING_ALGORITHM", "HS256")
    monkeypatch.setattr("app.api.internal.settings.INTERNAL_TOKEN_PRIVATE_KEY", "")
    monkeypatch.setattr("app.api.internal.settings.INTERNAL_TOKEN_PUBLIC_KEYS", TEST_INTERNAL_JWKS_JSON)

    with TestClient(app) as client:
        response = client.get("/internal/.well-known/jwks.json")

    assert response.status_code == 503
    assert "RSA signing algorithm" in response.json()["detail"]
