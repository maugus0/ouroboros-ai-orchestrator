"""Pytest configuration and shared fixtures."""

import os

import pytest

os.environ.setdefault("ALLOW_DB_FAILURE", "true")
os.environ.setdefault("USE_MOCK_DATA", "true")


@pytest.fixture
def mock_settings():
    return {
        "DB_HOST": "localhost",
        "DB_NAME": "test_db",
        "USE_MOCK_DATA": True,
        "ALLOW_DB_FAILURE": True,
    }
