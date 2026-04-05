"""Pytest configuration and shared fixtures."""

import os

import pytest

os.environ.setdefault("ALLOW_DB_FAILURE", "true")
os.environ.setdefault("USE_MOCK_DATA", "true")

# Auth0 test configuration
os.environ.setdefault("AUTH0_DOMAIN", "test-tenant.us.auth0.com")
os.environ.setdefault("AUTH0_API_AUDIENCE", "https://api.test.com")
os.environ.setdefault("AUTH0_ALGORITHMS", "RS256")


@pytest.fixture
def mock_settings():
    return {
        "DB_HOST": "localhost",
        "DB_NAME": "test_db",
        "USE_MOCK_DATA": True,
        "ALLOW_DB_FAILURE": True,
        "AUTH0_DOMAIN": "test-tenant.us.auth0.com",
        "AUTH0_API_AUDIENCE": "https://api.test.com",
    }
