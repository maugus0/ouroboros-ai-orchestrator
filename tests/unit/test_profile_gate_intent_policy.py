"""Intent-aware profile gate tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.profile_gate_service import ProfileGateService


@pytest.mark.asyncio
async def test_get_user_readiness_applies_intent_required_overlay():
    student_profile_client = MagicMock()
    student_profile_client.get_profile_status = AsyncMock(
        return_value={
            "user_id": "user-1",
            "completed": True,
            "missing_fields": [],
            "optional_missing_fields": ["target_study_country"],
            "updated_at": "2026-04-12T00:00:00",
        }
    )

    intent_registry = MagicMock()
    intent_registry.get_effective_required_fields.return_value = [
        "current_degree_level",
        "target_degree_level",
        "gpa",
        "gpa_scale",
        "intended_field_of_study",
        "target_study_country",
    ]
    intent_registry.get_effective_optional_fields.return_value = ["funding_source"]

    service = ProfileGateService(
        student_profile_client=student_profile_client,
        intent_registry_service=intent_registry,
    )

    readiness = await service.get_user_readiness(user_id="user-1", intent="scholarship_search")

    assert readiness["completed"] is False
    assert readiness["missing_required_fields"] == ["target_study_country"]
    assert readiness["missing_optional_fields"] == []


@pytest.mark.asyncio
async def test_get_user_readiness_defaults_missing_intent_to_profile_completion():
    student_profile_client = MagicMock()
    student_profile_client.get_profile_status = AsyncMock(
        return_value={
            "user_id": "user-1",
            "completed": True,
            "missing_fields": [],
            "optional_missing_fields": [],
            "updated_at": "2026-04-12T00:00:00",
        }
    )

    intent_registry = MagicMock()
    intent_registry.get_effective_required_fields.return_value = []
    intent_registry.get_effective_optional_fields.return_value = []

    service = ProfileGateService(
        student_profile_client=student_profile_client,
        intent_registry_service=intent_registry,
    )

    readiness = await service.get_user_readiness(user_id="user-1")

    student_profile_client.get_profile_status.assert_awaited_once_with(user_id="user-1", intent="profile_completion")
    intent_registry.get_effective_required_fields.assert_called_once_with("profile_completion")
    intent_registry.get_effective_optional_fields.assert_called_once_with("profile_completion")
    assert readiness["intent"] == "profile_completion"
    assert readiness["completed"] is True


@pytest.mark.asyncio
async def test_evaluate_gate_uses_intent_conditioned_completion():
    service = ProfileGateService()
    service.get_user_readiness = AsyncMock(
        return_value={
            "user_id": "user-1",
            "completed": False,
            "missing_fields": [],
            "optional_missing_fields": ["target_study_country"],
            "missing_required_fields": ["target_study_country"],
            "missing_optional_fields": [],
            "updated_at": "2026-04-12T00:00:00",
            "intent": "scholarship_search",
        }
    )

    gate = await service.evaluate_gate(user_id="user-1", intent="scholarship_search")

    assert gate["allowed"] is False
    assert gate["reason"] == "profile_incomplete_for_intent"
