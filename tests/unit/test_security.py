"""Tests for JWT token creation and validation."""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.security import create_access_token, create_refresh_token, decode_token


@pytest.fixture(scope="module")
def rsa_keys():
    """Generate a temporary RSA key pair for testing."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


ISSUER = "test-issuer"
AUDIENCE = "test-audience"


def test_create_and_decode_access_token(rsa_keys):
    private_pem, public_pem = rsa_keys
    token = create_access_token(
        payload={"sub": "user-123", "email": "test@example.com"},
        private_key=private_pem,
        issuer=ISSUER,
        audience=AUDIENCE,
    )
    claims = decode_token(token, public_key=public_pem, issuer=ISSUER, audience=AUDIENCE)
    assert claims["sub"] == "user-123"
    assert claims["type"] == "access"


def test_create_and_decode_refresh_token(rsa_keys):
    private_pem, public_pem = rsa_keys
    token = create_refresh_token(
        payload={"sub": "user-456"},
        private_key=private_pem,
        issuer=ISSUER,
        audience=AUDIENCE,
    )
    claims = decode_token(token, public_key=public_pem, issuer=ISSUER, audience=AUDIENCE)
    assert claims["sub"] == "user-456"
    assert claims["type"] == "refresh"


def test_decode_invalid_token(rsa_keys):
    _, public_pem = rsa_keys
    with pytest.raises(Exception):
        decode_token("not.a.token", public_key=public_pem, issuer=ISSUER, audience=AUDIENCE)
