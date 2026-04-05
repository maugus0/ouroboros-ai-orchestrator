"""
Shared database utilities for migration and seed scripts.

Provides a single source of truth for MySQL connection parameters,
ensuring consistency across run_migrations.py and seed_test_data.py.
"""
# pylint: disable=wrong-import-position

import re
import sys
from pathlib import Path

try:
    import mysql.connector
except ModuleNotFoundError as exc:
    sys.stderr.write(
        "Missing MySQL driver: cannot import mysql.connector "
        f"({exc.name!r} not found).\n\n"
        "  python -m pip install mysql-connector-python\n"
        "Or:  python -m pip install -r requirements-dev.txt\n"
    )
    raise SystemExit(1) from exc

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import settings  # noqa: E402

load_dotenv(ROOT_DIR / ".env")

_SAFE_DB_NAME = re.compile(r"^[a-zA-Z0-9_]+$")


def get_server_params() -> dict:
    """
    Connection parameters for MySQL server (no database selected).

    Use this for operations like CREATE DATABASE.
    """
    return {
        "host": settings.get_db_host(),
        "port": settings.get_db_port(),
        "user": settings.get_db_user(),
        "password": settings.get_db_password(),
        "charset": "utf8mb4",
    }


def get_connection():
    """
    Get a connection to the configured database.

    Returns a mysql.connector connection object with the database
    specified in settings (DB_NAME or MYSQL_DATABASE).
    """
    return mysql.connector.connect(
        **get_server_params(),
        database=settings.get_db_name(),
        collation="utf8mb4_unicode_ci",
    )


def ensure_database_exists() -> None:
    """
    Create the configured database if it does not exist.

    Without this, mysql.connector raises 1049 ProgrammingError:
    Unknown database '<DB_NAME>'.

    Validates DB name contains only safe characters (letters, digits, underscore).
    """
    db_name = settings.get_db_name()
    if not _SAFE_DB_NAME.match(db_name):
        raise ValueError(
            f"Refusing to create database with unsafe name {db_name!r}. "
            "Use only letters, digits, and underscores in DB_NAME / MYSQL_DATABASE."
        )

    conn = mysql.connector.connect(**get_server_params())
    cursor = conn.cursor()
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` " "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    cursor.close()
    conn.close()
    print(f"Database ready: {db_name}")
