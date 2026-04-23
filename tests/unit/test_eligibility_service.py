"""Unit tests for the EligibilityService."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.eligibility_service import EligibilityEvaluationInput, EligibilityResultsQuery, EligibilityService


def _build_mock_client():
    """Create a mocked eligibility client."""
    client = MagicMock()
    client.evaluate = AsyncMock(return_value={"success": True, "message": "OK", "data": {"match_result": {}}})
    client.get_results = AsyncMock(return_value={"success": True, "message": "OK", "data": {"items": []}})
    client.get_result_detail = AsyncMock(return_value={"success": True, "message": "OK", "data": {"id": "match-1"}})
    client.get_attribution_report = AsyncMock(
        return_value={"success": True, "message": "OK", "data": {"match_id": "match-1"}}
    )
    return client


@pytest.mark.asyncio
async def test_evaluate_builds_payload_from_authenticated_user():
    """Service should inject the orchestrator-authenticated user into the downstream payload."""
    mock_client = _build_mock_client()
    service = EligibilityService(client=mock_client)

    result = await service.evaluate(
        EligibilityEvaluationInput(
            user_id="user-123",
            entity_type="program",
            entity_id="program-456",
            user_profile={"gpa_normalized": 3.9},
            entity_data={"minimum_gpa": 3.5},
            include_attribution=False,
        ),
        trace_id="trace-abc",
    )

    assert result["success"] is True
    mock_client.evaluate.assert_awaited_once_with(
        {
            "user_id": "user-123",
            "entity_type": "program",
            "entity_id": "program-456",
            "user_profile": {"gpa_normalized": 3.9},
            "entity_data": {"minimum_gpa": 3.5},
            "include_attribution": False,
        },
        trace_id="trace-abc",
    )


@pytest.mark.asyncio
async def test_get_results_forwards_filters_and_pagination():
    """Service should forward result-list filters transparently."""
    mock_client = _build_mock_client()
    service = EligibilityService(client=mock_client)

    result = await service.get_results(
        EligibilityResultsQuery(
            user_id="user-123",
            entity_type="scholarship",
            page=2,
            page_size=5,
        ),
        trace_id="trace-xyz",
    )

    assert result["success"] is True
    mock_client.get_results.assert_awaited_once_with(
        user_id="user-123",
        query_params={"entity_type": "scholarship", "page": 2, "page_size": 5},
        trace_id="trace-xyz",
    )


@pytest.mark.asyncio
async def test_detail_and_attribution_delegate_to_client():
    """Service should delegate detail and attribution lookups without reshaping the response."""
    mock_client = _build_mock_client()
    service = EligibilityService(client=mock_client)

    detail = await service.get_result_detail(match_id="match-1", trace_id="trace-1")
    attribution = await service.get_attribution_report(match_id="match-1", trace_id="trace-2")

    assert detail["data"]["id"] == "match-1"
    assert attribution["data"]["match_id"] == "match-1"
    mock_client.get_result_detail.assert_awaited_once_with("match-1", trace_id="trace-1")
    mock_client.get_attribution_report.assert_awaited_once_with("match-1", trace_id="trace-2")
