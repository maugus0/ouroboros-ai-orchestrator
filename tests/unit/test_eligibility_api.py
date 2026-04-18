"""Unit tests for the orchestrator eligibility API."""

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import eligibility as eligibility_api
from app.middleware.auth_middleware import get_current_user_id
from app.services.eligibility_service import EligibilityEvaluationInput, EligibilityResultsQuery

app = FastAPI()
app.include_router(eligibility_api.router)
client = TestClient(app)


def _override_current_user_id() -> str:
    return "user-123"


def setup_function():
    """Reset dependency overrides before each test."""
    app.dependency_overrides.clear()


def teardown_function():
    """Reset dependency overrides after each test."""
    app.dependency_overrides.clear()


def test_evaluate_endpoint_injects_authenticated_user_and_trace_header(monkeypatch):
    mock_service = MagicMock()
    mock_service.evaluate = AsyncMock(
        return_value={"success": True, "message": "OK", "data": {"match_result": {"id": "match-1"}}}
    )
    monkeypatch.setattr(eligibility_api, "eligibility_service", mock_service)
    app.dependency_overrides[get_current_user_id] = _override_current_user_id

    response = client.post(
        "/api/v1/eligibility/evaluate",
        headers={"X-Trace-ID": "trace-123"},
        json={
            "entity_type": "program",
            "entity_id": "program-1",
            "user_profile": {"gpa_normalized": 3.8},
            "entity_data": {"minimum_gpa": 3.5},
            "include_attribution": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["match_result"]["id"] == "match-1"
    mock_service.evaluate.assert_awaited_once_with(
        EligibilityEvaluationInput(
            user_id="user-123",
            entity_type="program",
            entity_id="program-1",
            user_profile={"gpa_normalized": 3.8},
            entity_data={"minimum_gpa": 3.5},
            include_attribution=True,
        ),
        trace_id="trace-123",
    )


def test_get_results_endpoint_forwards_query_parameters(monkeypatch):
    mock_service = MagicMock()
    mock_service.get_results = AsyncMock(
        return_value={"success": True, "message": "OK", "data": {"items": [], "total": 0}}
    )
    monkeypatch.setattr(eligibility_api, "eligibility_service", mock_service)
    app.dependency_overrides[get_current_user_id] = _override_current_user_id

    response = client.get(
        "/api/v1/eligibility/results?entity_type=scholarship&page=2&page_size=5",
        headers={"X-Trace-ID": "trace-456"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["items"] == []
    mock_service.get_results.assert_awaited_once_with(
        EligibilityResultsQuery(
            user_id="user-123",
            entity_type="scholarship",
            page=2,
            page_size=5,
        ),
        trace_id="trace-456",
    )


def test_get_result_detail_and_attribution_endpoints(monkeypatch):
    mock_service = MagicMock()
    mock_service.get_result_detail = AsyncMock(
        return_value={"success": True, "message": "OK", "data": {"id": "match-1"}}
    )
    mock_service.get_attribution_report = AsyncMock(
        return_value={"success": True, "message": "OK", "data": {"match_id": "match-1"}}
    )
    monkeypatch.setattr(eligibility_api, "eligibility_service", mock_service)
    app.dependency_overrides[get_current_user_id] = _override_current_user_id

    detail_response = client.get("/api/v1/eligibility/results/match-1", headers={"X-Trace-ID": "trace-detail"})
    attribution_response = client.get(
        "/api/v1/eligibility/attribution/match-1",
        headers={"X-Trace-ID": "trace-attr"},
    )

    assert detail_response.status_code == 200
    assert attribution_response.status_code == 200
    assert detail_response.json()["data"]["id"] == "match-1"
    assert attribution_response.json()["data"]["match_id"] == "match-1"
    mock_service.get_result_detail.assert_awaited_once_with(match_id="match-1", trace_id="trace-detail")
    mock_service.get_attribution_report.assert_awaited_once_with(match_id="match-1", trace_id="trace-attr")
