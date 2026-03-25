"""Tests for the health-check endpoints."""

from fastapi.testclient import TestClient

from app.config import APP_VERSION
from app.main import app

client = TestClient(app)


def test_root_returns_healthy():
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["version"] == APP_VERSION


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert "version" in body
