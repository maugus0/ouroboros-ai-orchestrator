"""Seed test data for local development with Auth0 authentication."""

import sys
import uuid
from pathlib import Path

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


# Test users with Auth0 subject identifiers
# Create matching users in your Auth0 tenant for testing
TEST_USERS = [
    {
        "id": str(uuid.uuid4()),
        "auth0_sub": "auth0|test-student-001",
        "name": "Test Student",
        "email": "student@test.ouroboros.ai",
        "auth_provider": "auth0",
    },
    {
        "id": str(uuid.uuid4()),
        "auth0_sub": "auth0|demo-user-002",
        "name": "Demo User",
        "email": "demo@test.ouroboros.ai",
        "auth_provider": "auth0",
    },
    {
        "id": str(uuid.uuid4()),
        "auth0_sub": "google-oauth2|123456789",
        "name": "Google User",
        "email": "googleuser@gmail.com",
        "auth_provider": "auth0",
    },
]

INSERT_SQL = """
INSERT INTO users (id, auth0_sub, auth_provider, name, email, password_hash)
VALUES (%s, %s, %s, %s, %s, NULL)
ON DUPLICATE KEY UPDATE
    auth0_sub = VALUES(auth0_sub),
    auth_provider = VALUES(auth_provider),
    name = VALUES(name),
    updated_at = CURRENT_TIMESTAMP
"""


def seed():
    conn = get_connection()
    cursor = conn.cursor()

    print("Seeding test users with Auth0 identifiers...")
    print("-" * 50)

    for user in TEST_USERS:
        try:
            cursor.execute(
                INSERT_SQL,
                (
                    user["id"],
                    user["auth0_sub"],
                    user["auth_provider"],
                    user["name"],
                    user["email"],
                ),
            )
            print(f"  ✓ Seeded: {user['email']} ({user['auth0_sub']})")
        except mysql.connector.Error as err:
            print(f"  ✗ Failed: {user['email']} - {err}")

    conn.commit()
    cursor.close()
    conn.close()

    print("-" * 50)
    print("Test data seeded successfully.")
    print()
    print("NOTE: For testing, create matching users in your Auth0 tenant")
    print("      or update the auth0_sub values to match your test users.")


if __name__ == "__main__":
    seed()
