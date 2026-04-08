"""Seed OuroborosAI team members for local development and testing."""

import os
import sys
import uuid
from pathlib import Path

import bcrypt
import mysql.connector
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.logging import get_logger, setup_logging  # noqa: E402

setup_logging()
logger = get_logger(__name__)
load_dotenv()

# ── Team seed data ───────────────────────────────────────────────

SEED_USERS = [
    {
        "username": "Maugus",
        "first_name": "Ahan",
        "last_name": "Jaiswal",
        "email": "ahanjaiswal12@gmail.com",
        "phone_number": "+919818772178",
        "phone_country_code": "IN",
        "password": "Admin123@",
    },
    {
        "username": "NPT",
        "first_name": "Phu Truong",
        "last_name": "Nguyen",
        "email": "phu@gmail.com",
        "phone_number": "+6581234501",
        "phone_country_code": "SG",
        "password": "Admin123@",
    },
    {
        "username": "Feri",
        "first_name": "Feri",
        "last_name": "Setiawan",
        "email": "feri@gmail.com",
        "phone_number": "+6581234502",
        "phone_country_code": "SG",
        "password": "Admin123@",
    },
    {
        "username": "Stella",
        "first_name": "Xingyuan",
        "last_name": "Liu",
        "email": "xingyuan@gmail.com",
        "phone_number": "+6581234503",
        "phone_country_code": "SG",
        "password": "Admin123@",
    },
    {
        "username": "Lantya",
        "first_name": "Lanting",
        "last_name": "Zhao",
        "email": "lanting@gmail.com",
        "phone_number": "+6581234504",
        "phone_country_code": "SG",
        "password": "Admin123@",
    },
]


# ── Helpers ──────────────────────────────────────────────────────


def get_connection():
    """Direct MySQL connection for seeding."""
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USERNAME", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "ouroboros_orchestrator_db"),
    )


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def ensure_user(connection, user: dict) -> str:
    """Insert user if not exists (idempotent on username). Returns user UUID."""
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT id FROM users WHERE username = %s LIMIT 1", (user["username"],))
    row = cursor.fetchone()

    full_name = f"{user['first_name']} {user['last_name']}"

    if row:
        logger.info("  Already exists: %s (%s)", user["username"], full_name)
        cursor.close()
        return row["id"]

    user_id = str(uuid.uuid4())
    cursor.execute(
        """INSERT INTO users (id, username, phone_number, phone_country_code,
             phone_verified, password_hash, first_name, last_name, email,
             profile_completed, is_active)
        VALUES (%s, %s, %s, %s, FALSE, %s, %s, %s, %s, FALSE, TRUE)""",
        (
            user_id,
            user["username"],
            user["phone_number"],
            user["phone_country_code"],
            _hash_password(user["password"]),
            user["first_name"],
            user["last_name"],
            user["email"],
        ),
    )
    connection.commit()
    cursor.close()
    logger.info("  Created: %s (%s) — %s", user["username"], full_name, user_id)
    return user_id


# ── Main ─────────────────────────────────────────────────────────


def main():
    connection = get_connection()
    try:
        logger.info("Seeding OuroborosAI team members...")
        logger.info("-" * 60)

        for user in SEED_USERS:
            ensure_user(connection, user)

        logger.info("-" * 60)
        logger.info("")
        logger.info("=== Seed Users (credentials for testing) ===")
        logger.info("%-10s | %-22s | %-16s | %-26s", "Username", "Name", "Phone", "Email")
        logger.info("-" * 80)
        for u in SEED_USERS:
            logger.info(
                "%-10s | %-22s | %-16s | %-26s",
                u["username"],
                f"{u['first_name']} {u['last_name']}",
                u["phone_number"],
                u["email"],
            )
        logger.info("=" * 80)
        logger.info("All seed users share password: Admin123@")

    except Exception as exc:
        logger.error("Seeding failed: %s", exc)
        raise
    finally:
        if connection.is_connected():
            connection.close()


if __name__ == "__main__":
    main()
