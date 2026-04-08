"""Rules for when a user has finished the post-signup profile step."""

from typing import Any, Mapping, Optional

_VALID_INTERESTS = frozenset({"jobs", "startups", "research", "degree"})


def is_profile_complete(user: Optional[Mapping[str, Any]]) -> bool:
    """
    Profile is complete when all onboarding fields are set:

    ``email``, non-empty ``about_me``, non-empty ``profession``, and ``interest``
    (one of jobs / startups / research / degree).

    Signup already collects ``first_name`` / ``last_name``; those are not part of this gate.
    """
    if not user:
        return False
    email = (user.get("email") or "").strip()
    about = (user.get("about_me") or "").strip()
    profession = (user.get("profession") or "").strip()
    interest = user.get("interest")
    if not email or not about or not profession:
        return False
    if interest is None:
        return False
    return str(interest).strip().lower() in _VALID_INTERESTS
