"""Tests for JWT token generation and validation."""

# Pytest injects fixtures by parameter name.
# pylint: disable=redefined-outer-name

import pytest
from fastapi import HTTPException

from app.utils.jwt_util import JWTUtil


@pytest.fixture
def jwt_helper():
    return JWTUtil()


class TestAccessToken:
    def test_roundtrip(self, jwt_helper):
        token = jwt_helper.generate_access_token(user_id="u-123", username="alice", session_id="s-1")
        claims = jwt_helper.validate_token(token)
        assert claims["sub"] == "u-123"
        assert claims["username"] == "alice"
        assert claims["sid"] == "s-1"
        assert jwt_helper.is_access_token(claims) is True
        assert jwt_helper.is_refresh_token(claims) is False

    def test_rejects_garbage(self, jwt_helper):
        with pytest.raises(HTTPException) as exc:
            jwt_helper.validate_token("not.a.token")
        assert exc.value.status_code == 401


class TestRefreshToken:
    def test_roundtrip(self, jwt_helper):
        token = jwt_helper.generate_refresh_token(user_id="u-123", session_id="s-1", token_id="jti-abc")
        claims = jwt_helper.validate_token(token)
        assert claims["sub"] == "u-123"
        assert claims["sid"] == "s-1"
        assert claims["jti"] == "jti-abc"
        assert jwt_helper.is_refresh_token(claims) is True
        assert jwt_helper.is_access_token(claims) is False
