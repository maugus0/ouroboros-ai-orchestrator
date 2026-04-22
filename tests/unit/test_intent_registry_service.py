"""Unit tests for intent registry service."""

import json

import pytest

from app.services.intent_registry_service import IntentRegistryService


def test_detect_intent_scholarship_search():
    service = IntentRegistryService()

    intent = service.detect_intent("Can you find scholarship options for me?")

    assert intent == "scholarship_search"


def test_detect_intent_out_of_scope():
    service = IntentRegistryService()

    intent = service.detect_intent("Tell me a random joke")

    assert intent == "out_of_scope"


def test_detect_intent_program_discovery_from_discover_phrase():
    service = IntentRegistryService()

    intent = service.detect_intent("I want to discover a program suitable for me")

    assert intent == "program_discovery"


def test_detect_intent_program_discovery_from_discover_degree_phrase():
    service = IntentRegistryService()

    intent = service.detect_intent("I want to discover some master degree options")

    assert intent == "program_discovery"


def test_detect_intent_profile_completion_for_cv_upload():
    service = IntentRegistryService()

    intent = service.detect_intent("I'd like to upload my CV for processing and feedback")

    assert intent == "profile_completion"


def test_detect_intent_profile_completion_for_degree_clarification_answer():
    service = IntentRegistryService()

    intent = service.detect_intent("PhD")

    assert intent == "profile_completion"


def test_detect_intent_profile_completion_for_gpa_clarification_answer():
    service = IntentRegistryService()

    intent = service.detect_intent("3.8/4.0")

    assert intent == "profile_completion"


@pytest.mark.parametrize(
    "message",
    [
        "Can you write my SOP for NUS?",
        "I need a statement of purpose",
        "Help me draft a personal statement",
        "Create an application checklist",
        "What are my application deadlines?",
        "Draft a cover letter for this program",
    ],
)
def test_detect_intent_application_support_keywords(message):
    service = IntentRegistryService()

    intent = service.detect_intent(message)

    assert intent == "application_planning"


def test_effective_required_fields_include_base_and_intent_overlay(tmp_path):
    registry_path = tmp_path / "intent_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "version": "v1",
                "base_required_fields": ["gpa", "gpa_scale"],
                "intents": {
                    "scholarship_search": {
                        "required_fields": ["target_study_country"],
                        "optional_fields": ["funding_source"],
                    },
                    "out_of_scope": {
                        "required_fields": [],
                        "optional_fields": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    service = IntentRegistryService(registry_path=registry_path)

    required_fields = service.get_effective_required_fields("scholarship_search")

    assert required_fields == ["gpa", "gpa_scale", "target_study_country"]


def test_load_registry_falls_back_on_invalid_json(tmp_path):
    registry_path = tmp_path / "intent_registry.json"
    registry_path.write_text("{invalid-json", encoding="utf-8")
    service = IntentRegistryService(registry_path=registry_path)

    registry = service.load_registry()

    assert registry["version"] == "fallback-v1"
    assert "profile_completion" in registry["intents"]
