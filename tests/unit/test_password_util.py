"""Tests for password hashing utilities."""

from app.utils.password_util import hash_password, verify_password


def test_hash_returns_bcrypt_string():
    h = hash_password("StrongP@ss1")
    assert h.startswith("$2")
    assert h != "StrongP@ss1"


def test_verify_correct_password():
    h = hash_password("StrongP@ss1")
    assert verify_password("StrongP@ss1", h) is True


def test_verify_wrong_password():
    h = hash_password("StrongP@ss1")
    assert verify_password("WrongP@ss1", h) is False


def test_verify_empty_inputs():
    assert verify_password("", "") is False
    assert verify_password("test", "") is False
    assert verify_password("", "$2b$12$xxx") is False
