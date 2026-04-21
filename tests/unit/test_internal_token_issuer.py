"""Unit tests for internal service token issuer."""

import jwt

from app.security.internal_token_issuer import InternalTokenIssuer

TEST_HS256_KEY = "test-secret-key-with-at-least-32-bytes"


def test_issue_service_token_contains_required_claims_and_kid():
    issuer = InternalTokenIssuer(
        enabled=True,
        issuer="ouroboros-internal",
        ttl_seconds=120,
        signing_algorithm="HS256",
        private_key=TEST_HS256_KEY,
        active_kid="kid-v1",
        audience_map={"student-profile": "ouroboros.student-profile"},
    )

    token = issuer.issue_service_token(
        sub="user-1",
        sid="chat-1",
        trace_id="trace-1",
        aud="ouroboros.student-profile",
    )

    header = jwt.get_unverified_header(token)
    claims = jwt.decode(
        token,
        TEST_HS256_KEY,
        algorithms=["HS256"],
        audience="ouroboros.student-profile",
        issuer="ouroboros-internal",
    )

    assert header["kid"] == "kid-v1"
    assert claims["sub"] == "user-1"
    assert claims["sid"] == "chat-1"
    assert claims["trace_id"] == "trace-1"
    assert claims["aud"] == "ouroboros.student-profile"
    assert claims["iss"] == "ouroboros-internal"
    assert claims.get("jti")


def test_resolve_audience_falls_back_to_service_name_when_missing():
    issuer = InternalTokenIssuer(
        enabled=True,
        signing_algorithm="HS256",
        private_key=TEST_HS256_KEY,
        audience_map={"student-profile": "ouroboros.student-profile"},
    )

    assert issuer.resolve_audience("student-profile") == "ouroboros.student-profile"
    assert issuer.resolve_audience("eligibility-engine") == "eligibility-engine"
