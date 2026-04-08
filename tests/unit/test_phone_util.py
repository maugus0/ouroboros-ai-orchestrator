"""Tests for phone validation utilities."""

import pytest

from app.utils.phone_util import PhoneValidationError, mask_phone_number, validate_phone_number


class TestValidatePhoneNumber:
    def test_singapore_number(self):
        e164, cc = validate_phone_number("+6591234567")
        assert e164 == "+6591234567"
        assert cc == "SG"

    def test_india_number(self):
        e164, cc = validate_phone_number("+919876543210")
        assert e164 == "+919876543210"
        assert cc == "IN"

    def test_us_number(self):
        e164, cc = validate_phone_number("+12025551234")
        assert e164 == "+12025551234"
        assert cc == "US"

    def test_invalid_format_raises(self):
        with pytest.raises(PhoneValidationError):
            validate_phone_number("not-a-phone")

    def test_disallowed_country_raises(self):
        with pytest.raises(PhoneValidationError, match="not allowed"):
            validate_phone_number("+447911123456")


class TestMaskPhoneNumber:
    def test_masks_middle_digits(self):
        assert mask_phone_number("+6591234567") == "+65****4567"

    def test_short_number(self):
        assert mask_phone_number("+123") == "****"

    def test_empty(self):
        assert mask_phone_number("") == "****"
