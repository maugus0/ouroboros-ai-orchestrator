"""Unit tests for the EligibilityService."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

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


def _build_student_profile_client(profile_status=None, profile=None):
    client = MagicMock()
    client.get_profile_status = AsyncMock(return_value=profile_status or {"data": {"profile_id": "profile-123"}})
    client.get_profile = AsyncMock(
        return_value=profile
        or {
            "data": {
                "id": "profile-123",
                "nationality": "Indonesia",
                "target_degree_level": "master",
                "gpa_normalized": 3.8,
                "profile_json": {
                    "field_of_study": "Computer Science",
                    "skills": ["python", "ml"],
                    "completed_courses": ["algorithms"],
                    "target_country": "Singapore",
                },
            }
        }
    )
    return client


def _build_program_client(program=None):
    client = MagicMock()
    client.get_program_detail = AsyncMock(
        return_value=program
        or {
            "id": "program-456",
            "field": "Computer Science",
            "institution_country": "Singapore",
            "tuition_usd": 25000,
            "requirements": {
                "minimum_gpa": 3.5,
                "keywords": ["python", "ml"],
                "prerequisites": ["algorithms"],
            },
        }
    )
    return client


def _build_scholarship_client(scholarship=None):
    client = MagicMock()
    client.get_scholarship_detail = AsyncMock(
        return_value=scholarship
        or {
            "success": True,
            "data": {
                "id": "scholarship-789",
                "funding_amount": 12000,
                "eligibility_criteria": {
                    "minimum_gpa": 3.6,
                    "eligible_citizenships": ["indonesia"],
                    "eligible_fields_of_study": ["computer science"],
                    "required_degree_level": "master",
                },
            },
        }
    )
    return client


@pytest.mark.asyncio
async def test_evaluate_always_fetches_all_three_agents():
    """Service must always call all three agents instead of using pre-provided fallbacks."""
    mock_client = _build_mock_client()
    student_profile_client = _build_student_profile_client()
    program_client = _build_program_client()
    scholarship_client = _build_scholarship_client()
    service = EligibilityService(
        client=mock_client,
        student_profile_client=student_profile_client,
        program_discovery_client=program_client,
        scholarship_discovery_client=scholarship_client,
    )

    result = await service.evaluate(
        EligibilityEvaluationInput(
            user_id="user-123",
            entity_type="program",
            entity_id="program-456",
            include_attribution=False,
        ),
        trace_id="trace-abc",
    )

    assert result["success"] is True
    # All 3 agents must be called — mandatory, not fallback
    student_profile_client.get_profile_status.assert_awaited_once_with(
        "user-123", intent="eligibility_check", trace_id="trace-abc"
    )
    student_profile_client.get_profile.assert_awaited_once_with("profile-123", user_id="user-123", trace_id="trace-abc")
    program_client.get_program_detail.assert_awaited_once_with("program-456", user_id="user-123", trace_id="trace-abc")
    payload = mock_client.evaluate.await_args.args[0]
    assert payload["user_id"] == "user-123"
    assert payload["entity_type"] == "program"
    assert payload["entity_id"] == "program-456"
    assert payload["include_attribution"] is False
    assert payload["user_profile"]["citizenship"] == "Indonesia"
    assert payload["entity_data"]["minimum_gpa"] == 3.5


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


@pytest.mark.asyncio
async def test_evaluate_hydrates_missing_profile_and_program_data():
    mock_client = _build_mock_client()
    student_profile_client = _build_student_profile_client()
    program_client = _build_program_client()
    scholarship_client = _build_scholarship_client()
    service = EligibilityService(
        client=mock_client,
        student_profile_client=student_profile_client,
        program_discovery_client=program_client,
        scholarship_discovery_client=scholarship_client,
    )

    await service.evaluate(
        EligibilityEvaluationInput(
            user_id="user-123",
            entity_type="program",
            entity_id="program-456",
            user_profile=None,
            entity_data=None,
        ),
        trace_id="trace-hydrate",
    )

    student_profile_client.get_profile_status.assert_awaited_once_with(
        "user-123",
        intent="eligibility_check",
        trace_id="trace-hydrate",
    )
    student_profile_client.get_profile.assert_awaited_once_with(
        "profile-123",
        user_id="user-123",
        trace_id="trace-hydrate",
    )
    program_client.get_program_detail.assert_awaited_once_with(
        "program-456",
        user_id="user-123",
        trace_id="trace-hydrate",
    )
    payload = mock_client.evaluate.await_args.args[0]
    assert payload["user_profile"]["field_of_study"] == "Computer Science"
    assert payload["user_profile"]["citizenship"] == "Indonesia"
    assert payload["entity_data"]["minimum_gpa"] == 3.5
    assert payload["entity_data"]["keywords"] == ["python", "ml"]


@pytest.mark.asyncio
async def test_evaluate_hydrates_missing_scholarship_data():
    mock_client = _build_mock_client()
    scholarship_client = _build_scholarship_client()
    service = EligibilityService(
        client=mock_client,
        student_profile_client=_build_student_profile_client(),
        program_discovery_client=_build_program_client(),
        scholarship_discovery_client=scholarship_client,
    )

    await service.evaluate(
        EligibilityEvaluationInput(
            user_id="user-123",
            entity_type="scholarship",
            entity_id="scholarship-789",
        ),
        trace_id="trace-scholarship",
    )

    scholarship_client.get_scholarship_detail.assert_awaited_once_with(
        "scholarship-789",
        user_id="user-123",
        trace_id="trace-scholarship",
    )
    payload = mock_client.evaluate.await_args.args[0]
    assert payload["entity_data"]["required_degree_level"] == "master"
    assert payload["entity_data"]["eligible_fields_of_study"] == ["computer science"]
    # funding_amount from SDA must be mapped to award_amount_usd for the eligibility scorer
    assert payload["entity_data"]["award_amount_usd"] == 12000.0


@pytest.mark.asyncio
async def test_evaluate_requires_profile_when_hydration_finds_none():
    mock_client = _build_mock_client()
    service = EligibilityService(
        client=mock_client,
        student_profile_client=_build_student_profile_client(profile_status={"data": {}}),
        program_discovery_client=_build_program_client(),
        scholarship_discovery_client=_build_scholarship_client(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.evaluate(
            EligibilityEvaluationInput(
                user_id="user-123",
                entity_type="program",
                entity_id="program-456",
            )
        )

    assert exc_info.value.status_code == 424
