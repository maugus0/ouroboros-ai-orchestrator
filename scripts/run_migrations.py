"""Execute database migrations in numerical order with tracking."""

import re
from pathlib import Path

import mysql.connector
from db_utils import ensure_database_exists, get_connection

ROOT_DIR = Path(__file__).resolve().parents[1]

CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def get_applied_migrations(cursor) -> set:
    """Return set of already-applied migration filenames."""
    cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
    return {row[0] for row in cursor.fetchall()}


def record_migration(cursor, filename: str) -> None:
    """Record a migration as applied."""
    cursor.execute(
        "INSERT INTO schema_migrations (version) VALUES (%s)",
        (filename,),
    )


def run_migrations():
    """Run all pending SQL migration files in migrations/ directory."""
    migrations_dir = ROOT_DIR / "migrations"
    if not migrations_dir.exists():
        print("No migrations directory found.")
        return

    sql_files = sorted(f for f in migrations_dir.glob("*.sql") if re.match(r"^\d{3}_", f.name))

    if not sql_files:
        print("No migration files found.")
        return

    ensure_database_exists()
    conn = get_connection()
    cursor = conn.cursor()

    # Ensure migrations tracking table exists
    cursor.execute(CREATE_MIGRATIONS_TABLE)
    conn.commit()

    applied = get_applied_migrations(cursor)
    pending = [f for f in sql_files if f.name not in applied]

    if not pending:
        print("All migrations already applied.")
        cursor.close()
        conn.close()
        return

    print(f"Found {len(pending)} pending migration(s).\n")

    for sql_file in pending:
        print(f"Running migration: {sql_file.name}")
        sql = sql_file.read_text(encoding="utf-8")

        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                try:
                    cursor.execute(statement)
                except mysql.connector.Error as err:
                    print(f"  Error in {sql_file.name}: {err}")
                    raise

        record_migration(cursor, sql_file.name)
        conn.commit()
        print(f"  ✓ {sql_file.name} applied")

    cursor.close()
    conn.close()
    print("\nAll migrations applied successfully.")


if __name__ == "__main__":
    run_migrations()
