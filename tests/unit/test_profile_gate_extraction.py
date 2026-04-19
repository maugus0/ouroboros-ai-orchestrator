"""Unit tests for rule-first profile extraction from chat turns."""

# Tests intentionally validate internal cache behavior.
# pylint: disable=protected-access

import time

import pytest

from app.services.profile_gate_service import ProfileGateService


def test_extract_target_study_country_ambiguous_returns_both_options():
    content = "I am planning to study in Canada or Australia next year."

    extracted = ProfileGateService.extract_profile_fields_from_chat(
        content,
        ["target_study_country"],
    )

    assert extracted["target_study_country"] == ["Canada", "Australia"]


def test_extract_target_study_country_ignores_non_country_words():
    content = "I am planning to study in Mars or Australia next year."

    extracted = ProfileGateService.extract_profile_fields_from_chat(
        content,
        ["target_study_country"],
    )

    assert extracted["target_study_country"] == "Australia"


def test_extract_target_study_country_ignores_pronoun_us():
    content = "Can you help us choose the best intake timeline?"

    extracted = ProfileGateService.extract_profile_fields_from_chat(
        content,
        ["target_study_country"],
    )

    assert "target_study_country" not in extracted


def test_extract_target_study_country_supports_uppercase_us_and_canada():
    content = "I want to study in US or Canada."

    extracted = ProfileGateService.extract_profile_fields_from_chat(
        content,
        ["target_study_country"],
    )

    assert extracted["target_study_country"] == ["United States", "Canada"]


def test_extract_enrollment_timeline_ambiguous_returns_both_options():
    content = "I can start in Fall 2027 or Spring 2028 depending on admission timing."

    extracted = ProfileGateService.extract_profile_fields_from_chat(
        content,
        ["enrollment_timeline"],
    )

    assert extracted["enrollment_timeline"] == ["Fall 2027", "Spring 2028"]


def test_extract_enrollment_timeline_supports_year_first_season_format():
    content = "My options are 2028 fall or 2029 spring."

    extracted = ProfileGateService.extract_profile_fields_from_chat(
        content,
        ["enrollment_timeline"],
    )

    assert extracted["enrollment_timeline"] == ["Fall 2028", "Spring 2029"]


def test_extract_enrollment_timeline_supports_month_abbreviations():
    content = "I can start Sep 2027 or 2028 Jan intake."

    extracted = ProfileGateService.extract_profile_fields_from_chat(
        content,
        ["enrollment_timeline"],
    )

    assert extracted["enrollment_timeline"] == ["September 2027", "January 2028"]


def test_extract_intended_field_of_study_multiple_options():
    content = "My intended field of study is data science or computer science."

    extracted = ProfileGateService.extract_profile_fields_from_chat(
        content,
        ["intended_field_of_study"],
    )

    assert extracted["intended_field_of_study"] == ["Data Science", "Computer Science"]


def test_extract_intended_field_of_study_bare_answer():
    content = "Computer Science"

    extracted = ProfileGateService.extract_profile_fields_from_chat(
        content,
        ["intended_field_of_study"],
    )

    assert extracted["intended_field_of_study"] == "Computer Science"


def test_extract_funding_source_multiple_options():
    content = "I am looking for scholarship support, otherwise student loan is possible."

    extracted = ProfileGateService.extract_profile_fields_from_chat(
        content,
        ["funding_source"],
    )

    assert extracted["funding_source"] == ["scholarship", "loan"]


def test_extract_funding_source_preserves_mention_order():
    content = "I can rely on family support first, and scholarship as backup."

    extracted = ProfileGateService.extract_profile_fields_from_chat(
        content,
        ["funding_source"],
    )

    assert extracted["funding_source"] == ["family_support", "scholarship"]


def test_extract_funding_source_supports_grants_and_company_sponsorship():
    content = "I may use a government grant or company sponsorship."

    extracted = ProfileGateService.extract_profile_fields_from_chat(
        content,
        ["funding_source"],
    )

    assert extracted["funding_source"] == ["scholarship", "sponsorship"]


def test_extract_target_degree_level_from_bare_degree_answer():
    content = "PhD"

    extracted = ProfileGateService.extract_profile_fields_from_chat(
        content,
        ["target_degree_level"],
    )

    assert extracted["target_degree_level"] == "phd"


def test_bare_degree_answer_does_not_fill_intended_field_of_study():
    content = "PhD"

    extracted = ProfileGateService.extract_profile_fields_from_chat(
        content,
        ["target_degree_level", "intended_field_of_study"],
    )

    assert extracted["target_degree_level"] == "phd"
    assert "intended_field_of_study" not in extracted


def test_extract_candidates_include_confidence_metadata_for_ambiguous_country():
    content = "I am planning to study in Canada or Australia next year."

    extracted = ProfileGateService.extract_profile_field_candidates_from_chat(
        content,
        ["target_study_country"],
    )

    candidate = extracted["target_study_country"]
    assert candidate["value"] == ["Canada", "Australia"]
    assert candidate["confidence"] < 0.85
    assert candidate["reason"] == "ambiguous_country_candidates"


@pytest.mark.asyncio
async def test_collect_profile_updates_from_chat_skips_low_confidence_persistence():
    class _StubStudentProfileClient:
        called = False

        async def collect_from_chat(self, **_kwargs):
            self.called = True
            return {"data": {"applied_fields": []}}

    service = ProfileGateService(student_profile_client=_StubStudentProfileClient())

    result = await service.collect_profile_updates_from_chat(
        user_id="user-1",
        content="I am planning to study in Canada or Australia next year.",
        missing_fields=["target_study_country"],
        chat_id="chat-1",
        message_id="msg-1",
    )

    assert result is not None
    assert result["applied_fields"] == []
    assert "target_study_country" in result["pending_clarification_fields"]
    assert result["extraction_telemetry"]["candidate_count"] == 1
    assert result["extraction_telemetry"]["persisted_count"] == 0
    assert result["extraction_telemetry"]["clarification_count"] == 1
    assert result["extraction_telemetry"]["hit_rate"] == 0.0
    assert result["extraction_telemetry"]["clarification_rate"] == 1.0
    assert service.student_profile_client.called is False


@pytest.mark.asyncio
async def test_get_user_readiness_uses_short_ttl_cache_and_invalidation():
    class _StubStudentProfileClient:
        def __init__(self):
            self.calls = 0

        async def get_profile_status(self, user_id: str, intent: str | None = None):
            self.calls += 1
            return {
                "data": {
                    "user_id": user_id,
                    "completed": True,
                    "missing_fields": [],
                    "optional_missing_fields": [],
                    "updated_at": "2026-04-12T00:00:00",
                    "intent": intent,
                }
            }

    student_profile_client = _StubStudentProfileClient()
    service = ProfileGateService(
        student_profile_client=student_profile_client,
        agent_call_log_repo=object(),
        intent_registry_service=type(
            "_StubIntentRegistryService",
            (),
            {
                "get_effective_required_fields": staticmethod(lambda _intent: []),
                "get_effective_optional_fields": staticmethod(lambda _intent: []),
            },
        )(),
    )

    first = await service.get_user_readiness("user-1", intent="program_discovery")
    second = await service.get_user_readiness("user-1", intent="program_discovery")

    assert student_profile_client.calls == 1
    assert first == second

    service.invalidate_readiness_cache("user-1", "program_discovery")
    third = await service.get_user_readiness("user-1", intent="program_discovery")

    assert student_profile_client.calls == 2
    assert third["completed"] is True


@pytest.mark.asyncio
async def test_get_user_readiness_prunes_expired_and_overflow_entries():
    class _StubStudentProfileClient:
        async def get_profile_status(self, user_id: str, intent: str | None = None):
            return {
                "data": {
                    "user_id": user_id,
                    "completed": True,
                    "missing_fields": [],
                    "optional_missing_fields": [],
                    "updated_at": "2026-04-12T00:00:00",
                    "intent": intent,
                }
            }

    student_profile_client = _StubStudentProfileClient()
    service = ProfileGateService(
        student_profile_client=student_profile_client,
        agent_call_log_repo=object(),
        intent_registry_service=type(
            "_StubIntentRegistryService",
            (),
            {
                "get_effective_required_fields": staticmethod(lambda _intent: []),
                "get_effective_optional_fields": staticmethod(lambda _intent: []),
            },
        )(),
    )

    original_max_entries = ProfileGateService._READINESS_CACHE_MAX_ENTRIES
    original_ttl_seconds = ProfileGateService._READINESS_CACHE_TTL_SECONDS
    ProfileGateService._READINESS_CACHE.clear()
    ProfileGateService._READINESS_CACHE_MAX_ENTRIES = 2
    ProfileGateService._READINESS_CACHE_TTL_SECONDS = 3600

    try:
        key_one = service._readiness_cache_key("user-1", "program_discovery")
        key_two = service._readiness_cache_key("user-2", "program_discovery")
        key_three = service._readiness_cache_key("user-3", "program_discovery")

        ProfileGateService._READINESS_CACHE[key_one] = (
            time.monotonic() - 10,
            {"user_id": "user-1", "completed": True, "updated_at": "2026-04-12T00:00:00"},
        )

        await service.get_user_readiness("user-2", intent="program_discovery")
        await service.get_user_readiness("user-3", intent="program_discovery")

        assert key_one not in ProfileGateService._READINESS_CACHE
        assert key_two in ProfileGateService._READINESS_CACHE
        assert key_three in ProfileGateService._READINESS_CACHE
        assert len(ProfileGateService._READINESS_CACHE) == 2
    finally:
        ProfileGateService._READINESS_CACHE.clear()
        ProfileGateService._READINESS_CACHE_MAX_ENTRIES = original_max_entries
        ProfileGateService._READINESS_CACHE_TTL_SECONDS = original_ttl_seconds


def test_extract_country_correction_candidate_even_when_not_missing():
    content = "Not Canada, Australia instead."

    extracted = ProfileGateService.extract_profile_field_candidates_from_chat(
        content,
        [],
    )

    assert extracted["target_study_country"]["value"] == "Australia"
    assert extracted["target_study_country"]["is_correction"] is True
    assert extracted["target_study_country"]["confidence"] >= 0.9
