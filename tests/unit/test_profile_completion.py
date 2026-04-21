"""Tests for profile completion rules."""

import pytest

from app.utils.profile_completion import get_missing_profile_fields, is_profile_complete

_COMPLETE = {
    "gender": "female",
    "email": "a@b.com",
    "about_me": "Hi",
    "profession": "Dev",
    "interest": "startups",
}


@pytest.mark.parametrize(
    "row,expected",
    [
        (None, False),
        ({}, False),
        (_COMPLETE, True),
        ({**_COMPLETE, "interest": "degree"}, True),
        ({**_COMPLETE, "interest": "jobs"}, True),
        ({**_COMPLETE, "interest": "research"}, True),
        ({**_COMPLETE, "gender": "male"}, True),
        ({**_COMPLETE, "gender": "other"}, True),
        ({**_COMPLETE, "gender": "prefer_not_to_say"}, True),
        ({**_COMPLETE, "gender": None}, False),
        ({**_COMPLETE, "gender": "invalid"}, False),
        ({**_COMPLETE, "email": "  "}, False),
        ({**_COMPLETE, "about_me": ""}, False),
        ({**_COMPLETE, "profession": ""}, False),
        ({**_COMPLETE, "interest": None}, False),
    ],
)
def test_is_profile_complete(row, expected):
    assert is_profile_complete(row) is expected


def test_get_missing_profile_fields():
    missing = get_missing_profile_fields({"gender": "female", "email": "", "about_me": "Hi", "profession": None})
    assert missing == ["email", "profession", "interest"]
