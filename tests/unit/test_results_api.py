"""Unit tests for aggregated results API."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import results as results_api
from app.middleware.auth_middleware import get_current_user_id

# pylint: disable=protected-access


app = FastAPI()
app.include_router(results_api.router)
client = TestClient(app)


def _override_current_user_id() -> str:
    return "user-123"


def setup_function():
    app.dependency_overrides.clear()


def teardown_function():
    app.dependency_overrides.clear()


def test_discover_endpoint_returns_pipeline_response():
    mock_service = MagicMock()
    mock_service.discover = AsyncMock(
        return_value={
            "workflow_id": "wf-1",
            "status": "success",
            "version": 5,
            "dashboard": {"status": "success"},
        }
    )
    app.dependency_overrides[get_current_user_id] = _override_current_user_id
    app.dependency_overrides[results_api._get_result_aggregation_service] = lambda: mock_service

    response = client.post(
        "/api/v1/discover",
        json={"target_field": "Computer Science", "target_degree": "master", "limit": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workflow_id"] == "wf-1"
    assert payload["status"] == "success"
    mock_service.discover.assert_awaited_once()


def test_get_result_endpoint_returns_404_when_missing():
    mock_service = MagicMock()
    mock_service.get_workflow_result = AsyncMock(return_value=None)
    app.dependency_overrides[get_current_user_id] = _override_current_user_id
    app.dependency_overrides[results_api._get_result_aggregation_service] = lambda: mock_service

    response = client.get("/api/v1/results/wf-missing")
    assert response.status_code == 404


def test_get_dashboard_endpoint_returns_latest_dashboard():
    mock_service = MagicMock()
    mock_service.get_dashboard = AsyncMock(
        return_value={
            "has_results": True,
            "latest_workflow_id": "wf-1",
            "dashboard": {"status": "success"},
            "history": [],
        }
    )
    app.dependency_overrides[get_current_user_id] = _override_current_user_id
    app.dependency_overrides[results_api._get_result_aggregation_service] = lambda: mock_service

    response = client.get("/api/v1/dashboard?include_history=true&history_limit=10")
    assert response.status_code == 200
    payload = response.json()
    assert payload["has_results"] is True
    assert payload["latest_workflow_id"] == "wf-1"
    mock_service.get_dashboard.assert_awaited_once_with(
        user_id="user-123",
        include_history=True,
        history_limit=10,
    )
