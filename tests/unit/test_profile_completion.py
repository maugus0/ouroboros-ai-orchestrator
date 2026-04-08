"""Tests for profile completion rules."""

import pytest

from app.utils.profile_completion import is_profile_complete


@pytest.mark.parametrize(
    "row,expected",
    [
        (None, False),
        ({}, False),
        (
            {
                "email": "a@b.com",
                "about_me": "Hi",
                "profession": "Dev",
                "interest": "startups",
            },
            True,
        ),
        (
            {
                "email": "a@b.com",
                "about_me": "Hi",
                "profession": "Student",
                "interest": "degree",
            },
            True,
        ),
        (
            {
                "email": "a@b.com",
                "about_me": "Hi",
                "profession": "Dev",
                "interest": None,
            },
            False,
        ),
        (
            {
                "email": "  ",
                "about_me": "Hi",
                "profession": "Dev",
                "interest": "jobs",
            },
            False,
        ),
        (
            {
                "email": "a@b.com",
                "about_me": "",
                "profession": "Dev",
                "interest": "research",
            },
            False,
        ),
    ],
)
def test_is_profile_complete(row, expected):
    assert is_profile_complete(row) is expected
