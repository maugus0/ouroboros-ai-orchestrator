"""Execute database migrations in numerical order."""

import re
from pathlib import Path

import mysql.connector
from db_utils import ensure_database_exists, get_connection

ROOT_DIR = Path(__file__).resolve().parents[1]


def run_migrations():
    """Run all SQL migration files in migrations/ directory."""
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

    for sql_file in sql_files:
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

        conn.commit()
        print(f"  ✓ {sql_file.name} applied")

    cursor.close()
    conn.close()
    print("\nAll migrations applied successfully.")


if __name__ == "__main__":
    run_migrations()
