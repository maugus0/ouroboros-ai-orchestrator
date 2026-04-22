"""Tests for database migration runner configuration."""

from scripts import run_migrations


class _FakeCursor:
    def execute(self, _statement):
        return None

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
