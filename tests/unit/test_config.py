"""Tests for configuration loading."""

from app.config import settings


def test_settings_loaded():
    assert settings is not None
    assert settings.DB_HOST is not None


def test_db_host_fallback():
    host = settings.get_db_host()
    assert isinstance(host, str)
    assert len(host) > 0


def test_cors_origins_list():
    origins = settings.get_cors_origins_list()
    assert isinstance(origins, list)
    assert len(origins) >= 1


def test_allowed_country_codes():
    codes = settings.get_allowed_country_codes()
    assert isinstance(codes, list)
    assert "SG" in codes
    assert "US" in codes
