"""Execute database migrations in numerical order."""

import os
import re
import sys
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.logging import get_logger, setup_logging  # noqa: E402

setup_logging()
logger = get_logger(__name__)
load_dotenv()

MIGRATIONS_DIR = ROOT_DIR / "migrations"


def validate_db_name(name: str) -> str:
    """Validate database name — only alphanumeric + underscore, max 64 chars."""
    if not name or not name.strip():
        raise ValueError("Database name cannot be empty")
    if not re.match(r"^[A-Za-z0-9_]+$", name):
        raise ValueError(
            f"Invalid database name '{name}'. " "Only alphanumeric characters and underscores are allowed."
        )
    if len(name) > 64:
        raise ValueError(f"Database name '{name}' exceeds 64 characters")
    return name


def get_server_connection():
    """Connect to MySQL server without specifying a database."""
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USERNAME", "root"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def create_database_if_not_exists(connection, db_name: str) -> None:
    """Create the database if it doesn't exist."""
    validated = validate_db_name(db_name)
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{validated}` " "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        connection.commit()
        logger.info("Database '%s' ready", validated)
    except mysql.connector.Error as exc:
        logger.error("Error creating database: %s", exc)
        raise
    finally:
        cursor.close()


def strip_sql_comments(sql_content: str) -> str:
    """Remove single-line SQL comments before splitting on semicolons."""
    lines = []
    for line in sql_content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        if "--" in line:
            line = line[: line.index("--")]
        lines.append(line)
    return "\n".join(lines)


def run_migration_file(connection, sql_file: Path) -> None:
    """Run every statement in a single migration file (idempotent)."""
    cursor = connection.cursor()
    try:
        sql_content = sql_file.read_text(encoding="utf-8")
        cleaned = strip_sql_comments(sql_content)
        statements = [s.strip() for s in cleaned.split(";") if s.strip()]

        for statement in statements:
            try:
                cursor.execute(statement)
                connection.commit()
            except mysql.connector.Error as exc:
                error_msg = str(exc).lower()
                err_code = getattr(exc, "errno", None)
                is_expected = (
                    "already exists" in error_msg
                    or "duplicate" in error_msg
                    or err_code == 1061
                    or err_code == 1091
                    or "check that column/key exists" in error_msg
                )
                if is_expected:
                    logger.debug("  Skipped (already applied): %s", statement[:60])
                    connection.rollback()
                else:
                    logger.error("  Migration failed: %s — %s", sql_file.name, exc)
                    logger.error("  Statement: %s...", statement[:100])
                    connection.rollback()
                    raise

        logger.info("Ran migration: %s", sql_file.name)
    except mysql.connector.Error:
        cursor.close()
        raise
    except Exception as exc:
        logger.exception("Unexpected error in %s: %s", sql_file.name, exc)
        cursor.close()
        raise
    finally:
        cursor.close()


def run_migrations() -> None:
    """Run all .sql files in migrations/ in sorted order. Exits with 1 on failure."""
    db_name = os.getenv("DB_NAME", "ouroboros_orchestrator_db")
    try:
        db_name = validate_db_name(db_name)
    except ValueError as exc:
        logger.error("Invalid DB_NAME: %s", exc)
        sys.exit(1)

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        logger.info("No migration files found in %s", MIGRATIONS_DIR)
        return

    logger.info("Starting migrations for database: %s", db_name)
    connection = get_server_connection()

    try:
        create_database_if_not_exists(connection, db_name)
        connection.database = db_name
        logger.info("Found %d migration file(s)", len(sql_files))

        for sql_file in sql_files:
            try:
                run_migration_file(connection, sql_file)
            except (mysql.connector.Error, Exception) as exc:
                logger.error("Migration halted at %s: %s", sql_file.name, exc)
                if connection.is_connected():
                    connection.close()
                sys.exit(1)

        logger.info("All migrations completed successfully!")

    except mysql.connector.Error as exc:
        logger.error("Database error during migrations: %s", exc)
        sys.exit(1)
    except Exception as exc:
        logger.exception("Unexpected error during migrations: %s", exc)
        sys.exit(1)
    finally:
        if connection.is_connected():
            connection.close()
            logger.info("Database connection closed")


if __name__ == "__main__":
    run_migrations()
