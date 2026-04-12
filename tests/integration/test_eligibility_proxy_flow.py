"""Integration smoke tests for the orchestrator eligibility proxy."""

import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import eligibility as eligibility_api
from app.clients.eligibility_client import EligibilityClient
from app.middleware.auth_middleware import get_current_user_id
from app.services.eligibility_service import EligibilityService


def _override_current_user_id() -> str:
    return "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def eligibility_proxy_app(monkeypatch):
    """Create a small app that exercises the real eligibility proxy router."""
    app = FastAPI()
    app.include_router(eligibility_api.router)
    app.dependency_overrides[get_current_user_id] = _override_current_user_id

    service_token = os.getenv(
        "X_SERVICE_TOKEN",
        "ouroboros-ai-service-token-2024-secure-change-in-production",
    )
    eligibility_base_url = os.getenv("ELIGIBILITY_PROXY_TEST_URL", "http://localhost:8004")
    real_service = EligibilityService(
        client=EligibilityClient(
            base_url=eligibility_base_url,
            service_token=service_token,
            timeout=15,
        )
    )
    monkeypatch.setattr(eligibility_api, "eligibility_service", real_service)

    yield app

    app.dependency_overrides.clear()


def test_proxy_evaluate_and_fetch_results_against_real_eligibility_engine(eligibility_proxy_app):
    """Run a real orchestrator -> eligibility-engine proxy smoke flow."""
    client = TestClient(eligibility_proxy_app)
    entity_id = str(uuid.uuid4())

    evaluate_response = client.post(
        "/api/v1/eligibility/evaluate",
        headers={"X-Trace-ID": "proxy-trace-1"},
        json={
            "entity_type": "program",
            "entity_id": entity_id,
            "user_profile": {
                "gpa_normalized": 3.8,
                "major": "Computer Science",
                "technical_skills": ["Python", "Machine Learning", "AI"],
                "completed_courses": ["Algorithms", "Machine Learning"],
                "research_interests": "Natural language processing and multilingual AI systems",
                "preferred_locations": ["Sydney"],
                "budget_usd": 40000,
            },
            "entity_data": {
                "entity_type": "program",
                "minimum_gpa": 3.5,
                "keywords": ["Machine Learning", "AI", "NLP"],
                "prerequisites": ["Algorithms", "Machine Learning"],
                "location": "Sydney",
                "tuition_usd": 35000,
            },
            "include_attribution": False,
        },
    )

    if evaluate_response.status_code in (502, 504):
        pytest.skip(f"Eligibility engine unavailable for smoke test: {evaluate_response.text}")

    assert evaluate_response.status_code == 200
    evaluate_body = evaluate_response.json()
    assert evaluate_body["success"] is True
    match_result = evaluate_body["data"]["match_result"]
    assert match_result["entity_id"] == entity_id
    assert match_result["entity_type"] == "program"

    list_response = client.get(
        "/api/v1/eligibility/results",
        params={"entity_type": "program", "page": 1, "page_size": 10},
        headers={"X-Trace-ID": "proxy-trace-2"},
    )
    assert list_response.status_code == 200
    list_body = list_response.json()
    assert list_body["success"] is True
    assert any(item["id"] == match_result["id"] for item in list_body["data"]["items"])

    detail_response = client.get(
        "/api/v1/eligibility/results/{match_id}".format(match_id=match_result["id"]),
        headers={"X-Trace-ID": "proxy-trace-3"},
    )
    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    assert detail_body["success"] is True
    assert detail_body["data"]["id"] == match_result["id"]
