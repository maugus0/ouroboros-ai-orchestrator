"""Tests for OTP generation and expiry utilities."""

from datetime import datetime, timedelta, timezone

from app.utils.otp_util import can_request_new_otp, generate_otp, is_otp_expired


def test_generate_otp_length():
    otp = generate_otp(6)
    assert len(otp) == 6
    assert otp.isdigit()


def test_generate_otp_randomness():
    otps = {generate_otp() for _ in range(20)}
    assert len(otps) > 1


def test_not_expired_when_in_future():
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    assert is_otp_expired(future) is False


def test_expired_when_in_past():
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert is_otp_expired(past) is True


def test_expired_when_none():
    assert is_otp_expired(None) is True


def test_can_request_new_otp_first_time():
    allowed, wait = can_request_new_otp(None)
    assert allowed is True
    assert wait == 0


def test_can_request_after_cooldown():
    old = datetime.now(timezone.utc) - timedelta(seconds=60)
    allowed, _ = can_request_new_otp(old)
    assert allowed is True


def test_cannot_request_during_cooldown():
    recent = datetime.now(timezone.utc) - timedelta(seconds=5)
    allowed, wait = can_request_new_otp(recent)
    assert allowed is False
    assert wait > 0
