"""Intent registry loading, validation, and rule-first intent detection."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from app.core.logging import get_logger
from app.services.application_support_keywords import APPLICATION_SUPPORT_KEYWORDS

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

# --- Module-level keyword constants (avoid repeated allocation per call) ---

_CLARIFICATION_DEGREE_ANSWERS: frozenset[str] = frozenset(
    {
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
)

_PROGRAM_KEYWORDS: frozenset[str] = frozenset(
    {
        "program",
        "programs",
        "university",
        "universities",
        "school",
        "schools",
        "course",
        "courses",
        "major",
        "majors",
        "institution",
        "institutions",
        "college",
        "colleges",
        "degree",
        "degrees",
        "admission",
        "admissions",
        "graduate",
        "postgraduate",
        "undergraduate",
        "study",
        "studying",
    }
)

_RANKING_KEYWORDS: frozenset[str] = frozenset(
    {
        "ranking",
        "rankings",
        "ranked",
        "top",
        "best",
        "leading",
        "prestigious",
        "world class",
        "highly ranked",
        "qs",
        "qs world",
        "times higher education",
        "the ranking",
        "arwu",
        "shanghai ranking",
    }
)

_REQUIREMENT_KEYWORDS: frozenset[str] = frozenset(
    {
        "requirement",
        "requirements",
        "gpa requirement",
        "gmat",
        "gre",
        "toefl",
        "ielts",
        "sat",
        "act",
        "prerequisite",
        "prerequisites",
        "qualify",
        "qualified",
        "eligible",
        "eligibility",
        "need to apply",
        "how to apply",
    }
)

_COST_KEYWORDS: frozenset[str] = frozenset(
    {
        "tuition",
        "fee",
        "fees",
        "cost",
        "costs",
        "affordable",
        "expensive",
        "cheap",
        "budget",
        "price",
    }
)

_DEADLINE_KEYWORDS: frozenset[str] = frozenset(
    {
        "deadline",
        "deadlines",
        "due date",
        "application date",
        "apply by",
        "last date",
        "intake",
        "semester",
    }
)

_COMPARISON_KEYWORDS: frozenset[str] = frozenset(
    {
        "compare",
        "comparison",
        "vs",
        "versus",
        "better",
        "difference between",
        "which is better",
        "should i choose",
    }
)

_FIELD_KEYWORDS: frozenset[str] = frozenset(
    {
        "computer science",
        "data science",
        "artificial intelligence",
        "machine learning",
        "engineering",
        "mechanical",
        "electrical",
        "civil",
        "chemical",
        "biomedical",
        "business",
        "mba",
        "finance",
        "accounting",
        "marketing",
        "economics",
        "management",
        "medicine",
        "medical",
        "law",
        "legal",
        "psychology",
        "biology",
        "chemistry",
        "physics",
        "mathematics",
        "statistics",
        "environmental",
        "architecture",
        "design",
        "arts",
        "humanities",
        "social science",
        "political science",
        "international relations",
        "public policy",
        "public health",
        "nursing",
        "pharmacy",
        "education",
        "journalism",
        "communications",
        "media",
        "information technology",
        "cybersecurity",
        "blockchain",
        "fintech",
        "supply chain",
        "operations",
        "analytics",
        "stem",
    }
)

# Short acronyms (<=4 chars) need word-boundary matching to avoid false positives
# e.g., "mit" should not match "submit", "ucl" should not match "nucleus"
_SHORT_UNIVERSITY_ACRONYMS: frozenset[str] = frozenset(
    {
        "nus",
        "ntu",
        "smu",
        "sutd",
        "sit",
        "mit",
        "ucl",
        "lse",
        "lbs",
        "eth",
        "epfl",
        "cmu",
        "nyu",
        "usc",
        "ucla",
        "hec",
        "iit",
        "iim",
        "iisc",
        "bits",
        "snu",
        "hku",
        "cuhk",
        "hkust",
        "polyu",
        "unsw",
        "anu",
        "ubc",
        "tum",
        "rwth",
        "lmu",
        "kit",
        "kth",
        "dtu",
        "penn",
        "upenn",
        "umich",
        "uiuc",
        "kaist",
        "postech",
        "aalto",
    }
)

# Longer university names safe for substring matching
_UNIVERSITY_NAMES: frozenset[str] = frozenset(
    {
        "stanford",
        "harvard",
        "oxford",
        "cambridge",
        "berkeley",
        "yale",
        "princeton",
        "columbia",
        "caltech",
        "cornell",
        "brown",
        "dartmouth",
        "duke",
        "northwestern",
        "uchicago",
        "johns hopkins",
        "carnegie mellon",
        "georgia tech",
        "gatech",
        "michigan",
        "ut austin",
        "texas",
        "illinois",
        "purdue",
        "wisconsin",
        "washington",
        "eth zurich",
        "imperial",
        "kings college",
        "edinburgh",
        "manchester",
        "warwick",
        "bristol",
        "birmingham",
        "leeds",
        "nottingham",
        "southampton",
        "glasgow",
        "sheffield",
        "durham",
        "exeter",
        "insead",
        "iese",
        "london business school",
        "wharton",
        "kellogg",
        "booth",
        "sloan",
        "haas",
        "tuck",
        "ross",
        "fuqua",
        "stern",
        "tsinghua",
        "peking",
        "fudan",
        "shanghai jiao tong",
        "zhejiang",
        "nanjing",
        "wuhan",
        "tokyo",
        "kyoto",
        "osaka",
        "tohoku",
        "nagoya",
        "waseda",
        "keio",
        "seoul national",
        "yonsei",
        "korea university",
        "hanyang",
        "melbourne",
        "sydney",
        "queensland",
        "monash",
        "adelaide",
        "auckland",
        "toronto",
        "mcgill",
        "waterloo",
        "alberta",
        "montreal",
        "delft",
        "tu munich",
        "heidelberg",
        "tu berlin",
        "humboldt",
        "sorbonne",
        "ecole polytechnique",
        "sciences po",
        "bocconi",
        "politecnico",
        "tu vienna",
        "chalmers",
        "leiden",
        "amsterdam",
        "utrecht",
        "wageningen",
        "lund",
        "uppsala",
        "copenhagen",
        "technion",
        "hebrew university",
        "tel aviv",
    }
)

_UNIVERSITY_PATTERNS: tuple[str, ...] = (
    r"\bat\s+\w+(?:\s+\w+)?\s*(?:university|universities|college|colleges|institute|school|uni)\b",
    r"\b\w+(?:\s+\w+)?\s*(?:university|universities|college|colleges|institute|institutes|school|uni)\b",
    r"\buniversity\s+of\s+\w+(?:\s+\w+)?\b",
    r"\b\w+'s\s+(?:programs?|courses?|degrees?|graduate|mba|masters?|phd)\b",
    r"\bprograms?\s+at\s+\w+\b",
    r"\bstudying\s+at\s+\w+\b",
    r"\badmission\s+to\s+\w+\b",
    r"\babout\s+\w+(?:\s+\w+)?\s+(?:uni|university|college|institute)\b",
    r"\b\w+\s+uni\s+from\s+qs\b",
    r"\bdetails?\s+(?:about|of)\s+\w+(?:\s+\w+)?\s+(?:from\s+)?(?:qs|ranking|rankings)\b",
    r"\b\w+(?:\s+\w+)?\s+from\s+qs(?:\s+ranking|\s+rankings)?\b",
)

_APPLICATION_KEYWORDS: frozenset[str] = frozenset(
    {
        "apply",
        "application",
        "deadline",
        "how to apply",
        "apply to",
        "applying",
    }
)


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

    def detect_intent(self, content: str) -> str:  # pylint: disable=too-many-return-statements,too-many-branches
        """Use deterministic keyword rules for first-pass intent detection."""
        lowered = (content or "").strip().lower()
        if not lowered:
            return "profile_completion"

        if lowered in _CLARIFICATION_DEGREE_ANSWERS:
            return "profile_completion"

        if re.fullmatch(r"\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?", lowered) or re.fullmatch(r"\d+(?:\.\d+)?", lowered):
            return "profile_completion"

        if any(
            token in lowered
            for token in ("cv", "resume", "upload my", "transcript", "my document", "processing", "feedback")
        ):
            return "profile_completion"

        if self._is_application_support_query(lowered):
            return "application_planning"

        if self._is_program_discovery_query(lowered):
            if self._has_application_keywords(lowered) and self._has_university_mention(lowered):
                return "apply_to_named_school"
            return "program_discovery"

        if any(token in lowered for token in ("profile", "my gpa", "my degree", "my background", "update my")):
            return "profile_completion"

        if any(token in lowered for token in ("scholarship", "funding", "grant", "financial aid")):
            return "scholarship_search"

        if any(token in lowered for token in ("eligible", "eligibility", "qualify", "qualified")):
            if self._is_program_discovery_query(lowered):
                return "program_discovery"
            return "eligibility_check"

        return "out_of_scope"

    def _is_program_discovery_query(self, lowered: str) -> bool:
        """Check if query is related to programs, universities, or institutions."""
        if any(kw in lowered for kw in _PROGRAM_KEYWORDS):
            return True
        if any(kw in lowered for kw in _RANKING_KEYWORDS):
            return True
        if any(kw in lowered for kw in _REQUIREMENT_KEYWORDS):
            return True
        if any(kw in lowered for kw in _COST_KEYWORDS):
            return True
        if any(kw in lowered for kw in _DEADLINE_KEYWORDS):
            return True
        if any(kw in lowered for kw in _COMPARISON_KEYWORDS):
            return True
        if any(kw in lowered for kw in _FIELD_KEYWORDS):
            return True

        if self._has_university_mention(lowered):
            return True

        return False

    @staticmethod
    def _is_application_support_query(lowered: str) -> bool:
        """Check if query should be handled by application-support."""
        return any(token in lowered for token in APPLICATION_SUPPORT_KEYWORDS)

    def _has_university_mention(self, lowered: str) -> bool:
        """Check if query mentions a university by name or pattern."""
        if any(name in lowered for name in _UNIVERSITY_NAMES):
            return True

        for acronym in _SHORT_UNIVERSITY_ACRONYMS:
            if re.search(rf"\b{re.escape(acronym)}\b", lowered):
                return True

        for pattern in _UNIVERSITY_PATTERNS:
            if re.search(pattern, lowered):
                return True

        if "from qs" in lowered or "qs ranking" in lowered or "qs world" in lowered:
            return True

        return False

    @staticmethod
    def _has_application_keywords(lowered: str) -> bool:
        """Check if query has application-related keywords."""
        return any(token in lowered for token in _APPLICATION_KEYWORDS)

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
