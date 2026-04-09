"""Phone number validation, formatting, and masking utilities."""

from typing import Tuple

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat

from app.config import settings


class PhoneValidationError(Exception):
    """Raised when phone validation or country-code check fails."""


def validate_phone_number(phone: str) -> Tuple[str, str]:
    """Validate a phone string against the allowed-countries whitelist.

    Returns:
        (e164_string, iso_country_code)  e.g. ("+6591234567", "SG")

    Raises:
        PhoneValidationError on parse failure, invalid number, or blocked country.
    """
    try:
        parsed = phonenumbers.parse(phone, None)
    except NumberParseException as exc:
        raise PhoneValidationError(f"Could not parse phone number: {exc}") from exc

    if not phonenumbers.is_valid_number(parsed):
        raise PhoneValidationError("Invalid phone number")

    country = phonenumbers.region_code_for_number(parsed)
    allowed = settings.get_allowed_country_codes()

    if country not in allowed:
        raise PhoneValidationError(
            f"Phone numbers from {country} are not allowed. " f"Allowed countries: {', '.join(allowed)}"
        )

    e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
    return e164, country


def mask_phone_number(phone: str) -> str:
    """Mask a phone number for safe display — e.g. +65****5678.

    Parses the country calling code so variable-length prefixes (+1, +65, +91,
    +353 etc.) are preserved and only the subscriber digits are masked.
    """
    if not phone or len(phone) < 8:
        return "****"
    try:
        parsed = phonenumbers.parse(phone, None)
        cc_digits = str(parsed.country_code)
        prefix = f"+{cc_digits}"
        suffix = phone[-4:]
        middle_len = len(phone) - len(prefix) - 4
        if middle_len < 1:
            return "****"
        return prefix + "*" * middle_len + suffix
    except NumberParseException:
        return phone[:3] + "*" * (len(phone) - 7) + phone[-4:]
