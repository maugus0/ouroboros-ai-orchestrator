"""Intent registry loading, validation, and rule-first intent detection."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


_FALLBACK_REGISTRY: dict[str, Any] = {
    "version": "fallback-v1",
    "base_required_fields": [
        "current_degree_level",
        "target_degree_level",
        "gpa",
        "gpa_scale",
        "intended_field_of_study",
    ],
    "intents": {
        "profile_completion": {
            "agent": "student-profile",
            "required_fields": [],
            "optional_fields": ["target_study_country", "enrollment_timeline", "funding_source"],
            "fallback": {"type": "ask_required_profile_fields"},
        },
        "out_of_scope": {
            "agent": None,
            "required_fields": [],
            "optional_fields": [],
            "fallback": {
                "type": "boundary_message",
                "suggest_intents": ["scholarship_search", "program_discovery", "application_planning"],
            },
        },
    },
}


class IntentRegistryService:
    """Loads and serves intent policy used by chat orchestration."""

    def __init__(self, registry_path: Optional[Path] = None) -> None:
        self._registry_path = registry_path or Path(__file__).resolve().parents[1] / "configs" / "intent_registry.json"
        self._registry_cache: Optional[dict[str, Any]] = None

    def load_registry(self) -> dict[str, Any]:
        """Load and validate the configured registry, with safe fallback."""
        if self._registry_cache is not None:
            return self._registry_cache

        try:
            with self._registry_path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            validated = self._validate_registry(raw)
            self._registry_cache = validated
            return validated
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("intent_registry_load_failed", path=str(self._registry_path), error=str(exc))
            self._registry_cache = dict(_FALLBACK_REGISTRY)
            return self._registry_cache

    def detect_intent(self, content: str) -> str:
        """Use deterministic keyword rules for first-pass intent detection."""
        lowered = (content or "").strip().lower()
        if not lowered:
            return "profile_completion"

        clarification_degree_answers = {
            "phd",
            "doctorate",
            "doctoral",
            "master",
            "masters",
            "msc",
            "m.sc",
            "ms",
            "mba",
            "bachelor",
            "bachelors",
            "bsc",
            "b.sc",
            "bs",
            "undergraduate",
        }
        if lowered in clarification_degree_answers:
            return "profile_completion"

        if re.fullmatch(r"\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?", lowered) or re.fullmatch(r"\d+(?:\.\d+)?", lowered):
            return "profile_completion"

        if any(token in lowered for token in ["discover", "find", "search", "explore"]):
            if any(token in lowered for token in ["program", "university", "school", "course", "major"]):
                return "program_discovery"
            if any(token in lowered for token in ["scholarship", "funding", "grant"]):
                return "scholarship_search"

        if any(token in lowered for token in ["scholarship", "funding", "grant", "financial aid"]):
            return "scholarship_search"
        if any(token in lowered for token in ["program", "major", "course", "university", "school"]):
            if any(token in lowered for token in ["apply", "application", "deadline", "requirements"]):
                return "apply_to_named_school"
            return "program_discovery"
        if any(token in lowered for token in ["eligible", "eligibility", "qualify", "qualified", "requirements"]):
            return "eligibility_check"
        if any(
            token in lowered
            for token in ["application plan", "application timeline", "statement of purpose", "cover letter"]
        ):
            return "application_planning"
        if any(
            token in lowered
            for token in ["cv", "resume", "upload", "transcript", "document", "processing", "analysis", "feedback"]
        ):
            return "profile_completion"
        if any(token in lowered for token in ["profile", "my gpa", "my degree", "my background", "update my"]):
            return "profile_completion"

        return "out_of_scope"

    def get_policy(self, intent: str) -> dict[str, Any]:
        """Return policy object for an intent, falling back to out-of-scope."""
        registry = self.load_registry()
        intents = registry.get("intents") if isinstance(registry, dict) else None
        if not isinstance(intents, dict):
            return dict(_FALLBACK_REGISTRY["intents"]["out_of_scope"])

        policy = intents.get(intent)
        if isinstance(policy, dict):
            return policy

        out_of_scope = intents.get("out_of_scope")
        if isinstance(out_of_scope, dict):
            return out_of_scope
        return dict(_FALLBACK_REGISTRY["intents"]["out_of_scope"])

    def get_effective_required_fields(self, intent: str) -> list[str]:
        """Return base required fields plus intent-specific required overlays."""
        registry = self.load_registry()
        base_required = registry.get("base_required_fields") if isinstance(registry, dict) else []
        if not isinstance(base_required, list):
            base_required = []

        policy = self.get_policy(intent)
        intent_required = policy.get("required_fields") if isinstance(policy, dict) else []
        if not isinstance(intent_required, list):
            intent_required = []

        ordered: list[str] = []
        for field in [*base_required, *intent_required]:
            if isinstance(field, str) and field and field not in ordered:
                ordered.append(field)
        return ordered

    def get_effective_optional_fields(self, intent: str) -> list[str]:
        """Return optional fields configured for an intent."""
        policy = self.get_policy(intent)
        optional_fields = policy.get("optional_fields") if isinstance(policy, dict) else []
        if not isinstance(optional_fields, list):
            return []

        return [field for field in optional_fields if isinstance(field, str) and field]

    @staticmethod
    def _validate_registry(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("intent registry must be an object")

        base_required = raw.get("base_required_fields")
        intents = raw.get("intents")
        if not isinstance(base_required, list):
            raise ValueError("base_required_fields must be a list")
        if not isinstance(intents, dict) or not intents:
            raise ValueError("intents must be a non-empty object")

        for intent_name, policy in intents.items():
            if not isinstance(intent_name, str) or not intent_name:
                raise ValueError("intent keys must be non-empty strings")
            if not isinstance(policy, dict):
                raise ValueError(f"policy for {intent_name} must be an object")
            required_fields = policy.get("required_fields", [])
            optional_fields = policy.get("optional_fields", [])
            if not isinstance(required_fields, list):
                raise ValueError(f"required_fields for {intent_name} must be a list")
            if not isinstance(optional_fields, list):
                raise ValueError(f"optional_fields for {intent_name} must be a list")

        return raw
