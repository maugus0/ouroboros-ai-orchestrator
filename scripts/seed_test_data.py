"""Seed test data for local development."""

import sys
import uuid
from pathlib import Path

import bcrypt
import mysql.connector
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import settings

load_dotenv(ROOT_DIR / ".env")


def get_connection():
    return mysql.connector.connect(
        host=settings.get_db_host(),
        port=settings.get_db_port(),
        database=settings.get_db_name(),
        user=settings.get_db_user(),
        password=settings.get_db_password(),
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
    )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


TEST_USERS = [
    {
        "id": str(uuid.uuid4()),
        "name": "Test Student",
        "email": "student@test.ouroboros.ai",
        "password": "TestPassword123!",
    },
    {
        "id": str(uuid.uuid4()),
        "name": "Demo User",
        "email": "demo@test.ouroboros.ai",
        "password": "DemoPassword123!",
    },
]

INSERT_SQL = """
INSERT INTO users (id, name, email, password_hash)
VALUES (%s, %s, %s, %s)
ON DUPLICATE KEY UPDATE updated_at = CURRENT_TIMESTAMP
"""


def seed():
    conn = get_connection()
    cursor = conn.cursor()

    for user in TEST_USERS:
        cursor.execute(
            INSERT_SQL,
            (user["id"], user["name"], user["email"], hash_password(user["password"])),
        )
        print(f"  Seeded: {user['email']}")

    conn.commit()
    cursor.close()
    conn.close()
    print("\nTest data seeded successfully.")


if __name__ == "__main__":
    seed()
