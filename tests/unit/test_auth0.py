"""Tests for Auth0 JWT validation and JWKS handling."""

# Pytest injects fixtures by parameter name; names match the fixture definition.
# pylint: disable=redefined-outer-name,protected-access

import base64
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jose import jwt

from app.core import auth0


@pytest.fixture(scope="module")
def rsa_key_pair():
    """Generate a temporary RSA key pair for testing."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_key = private_key.public_key()
    public_numbers = public_key.public_numbers()
    return private_pem, public_key, public_numbers


@pytest.fixture
def mock_jwks(rsa_key_pair):
    """Create a mock JWKS response matching the test key pair."""
    _, _, public_numbers = rsa_key_pair

    def int_to_base64url(n: int, length: int) -> str:
        return base64.urlsafe_b64encode(n.to_bytes(length, "big")).decode().rstrip("=")

    n_bytes = (public_numbers.n.bit_length() + 7) // 8
    e_bytes = (public_numbers.e.bit_length() + 7) // 8

    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": "test-key-id",
                "use": "sig",
                "n": int_to_base64url(public_numbers.n, n_bytes),
                "e": int_to_base64url(public_numbers.e, e_bytes),
            }
        ]
    }


@pytest.fixture
def valid_token(rsa_key_pair):
    """Create a valid JWT token for testing."""
    private_pem, _, _ = rsa_key_pair
    now = int(time.time())
    payload = {
        "sub": "auth0|test-user-123",
        "email": "test@example.com",
        "name": "Test User",
        "iss": "https://test-tenant.us.auth0.com/",
        "aud": "https://api.test.com",
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": "test-key-id"})


@pytest.fixture
def expired_token(rsa_key_pair):
    """Create an expired JWT token for testing."""
    private_pem, _, _ = rsa_key_pair
    now = int(time.time())
    payload = {
        "sub": "auth0|test-user-123",
        "iss": "https://test-tenant.us.auth0.com/",
        "aud": "https://api.test.com",
        "iat": now - 7200,
        "exp": now - 3600,
    }
    return jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": "test-key-id"})


@pytest.fixture(autouse=True)
def clear_jwks_cache():
    """Clear JWKS cache before and after each test."""
    auth0.clear_jwks_cache()
    yield
    auth0.clear_jwks_cache()


class TestGetJWKS:
    """Tests for JWKS fetching and caching."""

    @pytest.mark.asyncio
    async def test_fetches_jwks_on_first_call(self, mock_jwks):
        """JWKS should be fetched from Auth0 on first call."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_jwks
        mock_response.raise_for_status = MagicMock()

        with patch("app.core.auth0.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            with patch("app.core.auth0.settings") as mock_settings:
                mock_settings.auth0_jwks_uri = "https://test.auth0.com/.well-known/jwks.json"

                result = await auth0.get_jwks()

                assert result == mock_jwks
                assert "keys" in result

    @pytest.mark.asyncio
    async def test_uses_cache_on_subsequent_calls(self, mock_jwks):
        """JWKS should be cached and reused."""
        auth0._JwksCache.data = mock_jwks
        auth0._JwksCache.fetched_at = time.time()

        with patch("app.core.auth0.httpx.AsyncClient") as mock_client:
            result = await auth0.get_jwks()

            mock_client.assert_not_called()
            assert result == mock_jwks

    @pytest.mark.asyncio
    async def test_refreshes_expired_cache(self, mock_jwks):
        """JWKS cache should be refreshed after TTL expires."""
        auth0._JwksCache.data = {"old": "data"}
        auth0._JwksCache.fetched_at = time.time() - auth0.JWKS_CACHE_TTL_SECONDS - 100

        mock_response = MagicMock()
        mock_response.json.return_value = mock_jwks
        mock_response.raise_for_status = MagicMock()

        with patch("app.core.auth0.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            with patch("app.core.auth0.settings") as mock_settings:
                mock_settings.auth0_jwks_uri = "https://test.auth0.com/.well-known/jwks.json"

                result = await auth0.get_jwks()

                assert result == mock_jwks


class TestValidateAuth0Token:
    """Tests for Auth0 token validation."""

    @pytest.mark.asyncio
    async def test_validates_valid_token(self, mock_jwks, valid_token):
        """Valid token should return decoded payload."""
        with patch.object(auth0, "get_jwks", return_value=mock_jwks):
            with patch("app.core.auth0.settings") as mock_settings:
                mock_settings.get_auth0_algorithms.return_value = ["RS256"]
                mock_settings.AUTH0_API_AUDIENCE = "https://api.test.com"
                mock_settings.auth0_issuer = "https://test-tenant.us.auth0.com/"

                payload = await auth0.validate_auth0_token(valid_token)

                assert payload["sub"] == "auth0|test-user-123"
                assert payload["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_rejects_expired_token(self, mock_jwks, expired_token):
        """Expired token should raise 401."""
        with patch.object(auth0, "get_jwks", return_value=mock_jwks):
            with patch("app.core.auth0.settings") as mock_settings:
                mock_settings.get_auth0_algorithms.return_value = ["RS256"]
                mock_settings.AUTH0_API_AUDIENCE = "https://api.test.com"
                mock_settings.auth0_issuer = "https://test-tenant.us.auth0.com/"

                with pytest.raises(HTTPException) as exc_info:
                    await auth0.validate_auth0_token(expired_token)

                assert exc_info.value.status_code == 401
                assert "expired" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_rejects_invalid_token(self, mock_jwks):
        """Invalid token should raise 401."""
        with patch.object(auth0, "get_jwks", return_value=mock_jwks):
            with pytest.raises(HTTPException) as exc_info:
                await auth0.validate_auth0_token("not.a.valid.token")

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_rejects_token_with_wrong_key(self, mock_jwks):
        """Token signed with wrong key should raise 401."""
        different_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        different_pem = different_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()

        now = int(time.time())
        wrong_key_token = jwt.encode(
            {"sub": "test", "iss": "https://test.com/", "aud": "test", "exp": now + 3600},
            different_pem,
            algorithm="RS256",
            headers={"kid": "test-key-id"},
        )

        with patch.object(auth0, "get_jwks", return_value=mock_jwks):
            with patch("app.core.auth0.settings") as mock_settings:
                mock_settings.get_auth0_algorithms.return_value = ["RS256"]
                mock_settings.AUTH0_API_AUDIENCE = "test"
                mock_settings.auth0_issuer = "https://test.com/"

                with pytest.raises(HTTPException) as exc_info:
                    await auth0.validate_auth0_token(wrong_key_token)

                assert exc_info.value.status_code == 401


class TestGetRSAKey:
    """Tests for RSA key extraction from JWKS."""

    def test_extracts_matching_key(self, mock_jwks, valid_token):
        """Should extract key matching token's kid."""
        key = auth0._get_rsa_key(mock_jwks, valid_token)

        assert key is not None
        assert key["kid"] == "test-key-id"
        assert key["kty"] == "RSA"

    def test_returns_none_for_missing_kid(self, mock_jwks, rsa_key_pair):
        """Should return None if no matching key found."""
        private_pem, _, _ = rsa_key_pair
        token = jwt.encode(
            {"sub": "test"},
            private_pem,
            algorithm="RS256",
            headers={"kid": "non-existent-key"},
        )

        key = auth0._get_rsa_key(mock_jwks, token)

        assert key is None

    def test_returns_none_for_invalid_token(self, mock_jwks):
        """Should return None for malformed token."""
        key = auth0._get_rsa_key(mock_jwks, "not-a-token")

        assert key is None


class TestClearJWKSCache:
    """Tests for cache clearing utility."""

    def test_clears_cache(self, mock_jwks):
        """Cache should be cleared."""
        auth0._JwksCache.data = mock_jwks
        auth0._JwksCache.fetched_at = time.time()

        auth0.clear_jwks_cache()

        assert auth0._JwksCache.data is None
        assert auth0._JwksCache.fetched_at == 0
