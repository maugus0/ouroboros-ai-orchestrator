"""Tests for database migration runner configuration."""

from scripts import run_migrations


class _FakeCursor:
    with_rows = False

    def __init__(self):
        self._nextset_calls = 0

    def execute(self, _statement):
        return None

    def fetchall(self):
        return []

    def nextset(self):
        self._nextset_calls += 1
        return False

    def close(self):
        return None


class _FakeConnection:
    def cursor(self):
        return _FakeCursor()


def test_get_server_connection_prefers_migration_credentials(monkeypatch):
    captured = {}

    def _fake_connect(**kwargs):
        captured.update(kwargs)
        return _FakeConnection()

    monkeypatch.setenv("DB_HOST", "mysql")
    monkeypatch.setenv("DB_PORT", "3306")
    monkeypatch.setenv("DB_USERNAME", "app-user")
    monkeypatch.setenv("DB_PASSWORD", "app-password")
    monkeypatch.setenv("MIGRATION_DB_USERNAME", "root")
    monkeypatch.setenv("MIGRATION_DB_PASSWORD", "root-password")
    monkeypatch.setattr(run_migrations.mysql.connector, "connect", _fake_connect)

    run_migrations.get_server_connection()

    assert captured["host"] == "mysql"
    assert captured["port"] == 3306
    assert captured["user"] == "root"
    assert captured["password"] == "root-password"


def test_drain_cursor_results_consumes_rows_and_nextset():
    class _CursorWithResults(_FakeCursor):
        with_rows = True

        def __init__(self):
            super().__init__()
            self.fetchall_calls = 0

        def fetchall(self):
            self.fetchall_calls += 1
            return []

        def nextset(self):
            self._nextset_calls += 1
            return self._nextset_calls < 2

    cursor = _CursorWithResults()
    run_migrations.drain_cursor_results(cursor)

    assert cursor.fetchall_calls >= 2


def test_drain_cursor_results_handles_missing_nextset():
    class _CursorNoNextset:
        with_rows = False

    run_migrations.drain_cursor_results(_CursorNoNextset())
