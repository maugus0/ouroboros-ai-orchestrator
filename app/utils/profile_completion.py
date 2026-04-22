"""Rules for when a user has finished the post-signup profile step."""

from typing import Any, Mapping, Optional

_VALID_GENDERS = frozenset({"male", "female", "other", "prefer_not_to_say"})
_VALID_INTERESTS = frozenset({"jobs", "startups", "research", "degree"})


def is_profile_complete(user: Optional[Mapping[str, Any]]) -> bool:
    """
    Profile is complete when all onboarding fields are set:

    ``gender`` (one of male / female / other / prefer_not_to_say),
    ``email``, non-empty ``about_me``, non-empty ``profession``, and ``interest``
    (one of jobs / startups / research / degree).

    Signup already collects ``first_name`` / ``last_name``; those are not part of this gate.
    """
    return not get_missing_profile_fields(user)


def get_missing_profile_fields(user: Optional[Mapping[str, Any]]) -> list[str]:
    """Return the profile fields that still need user input."""
    if not user:
        return ["gender", "email", "about_me", "profession", "interest"]

    missing: list[str] = []

    gender = user.get("gender")
    if gender is None or str(gender).strip().lower() not in _VALID_GENDERS:
        missing.append("gender")

    if not (user.get("email") or "").strip():
        missing.append("email")
    if not (user.get("about_me") or "").strip():
        missing.append("about_me")
    if not (user.get("profession") or "").strip():
        missing.append("profession")

    interest = user.get("interest")
    if interest is None or str(interest).strip().lower() not in _VALID_INTERESTS:
        missing.append("interest")

    return missing
