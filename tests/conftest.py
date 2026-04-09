"""Pytest configuration and shared fixtures."""

import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

os.environ.setdefault("ALLOW_DB_FAILURE", "true")
os.environ.setdefault("USE_MOCK_DATA", "true")

# Generate throwaway RSA key pair for tests so JWT encode/decode works.
_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_private_pem = _private_key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
_public_pem = (
    _private_key.public_key()
    .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    .decode()
)

os.environ.setdefault("JWT_PRIVATE_KEY", _private_pem)
os.environ.setdefault("JWT_PUBLIC_KEY", _public_pem)
os.environ.setdefault("JWT_ISSUER", "ouroboros.ai/auth")
os.environ.setdefault("JWT_AUDIENCE", "ouroboros-api")


@pytest.fixture
def rsa_keys():
    """Return the test key-pair as (private_pem, public_pem)."""
    return _private_pem, _public_pem


@pytest.fixture
def mock_settings():
    return {
        "DB_HOST": "localhost",
        "DB_NAME": "test_db",
        "USE_MOCK_DATA": True,
        "ALLOW_DB_FAILURE": True,
    }
