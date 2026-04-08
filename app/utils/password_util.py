"""Password hashing utilities using bcrypt (cost factor 12)."""

import bcrypt

BCRYPT_COST = 12


def hash_password(password: str) -> str:
    """Hash a plaintext password. Returns a bcrypt string."""
    salt = bcrypt.gensalt(rounds=BCRYPT_COST)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Compare plaintext against a stored bcrypt hash."""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
