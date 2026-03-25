"""Request and response schemas exchanged with agent microservices."""

from pydantic import BaseModel

# ── Student Profile Agent ──────────────────────────────────────────


class StudentProfileRequest(BaseModel):
    user_id: str
    cv_text: str | None = None
    cv_file_url: str | None = None


class StudentProfileResponse(BaseModel):
    user_id: str
    parsed_profile: dict


# ── Program Discovery Agent ───────────────────────────────────────


class ProgramDiscoveryRequest(BaseModel):
    user_id: str
    profile: dict


class ProgramDiscoveryResponse(BaseModel):
    programs: list[dict]


# ── Scholarship Discovery Agent ──────────────────────────────────


class ScholarshipDiscoveryRequest(BaseModel):
    user_id: str
    profile: dict
    programs: list[dict] | None = None


class ScholarshipDiscoveryResponse(BaseModel):
    scholarships: list[dict]


# ── Eligibility Engine Agent ─────────────────────────────────────


class EligibilityRequest(BaseModel):
    user_id: str
    profile: dict
    programs: list[dict]
    scholarships: list[dict]


class EligibilityResponse(BaseModel):
    matches: list[dict]


# ── Application Support Agent ────────────────────────────────────


class ApplicationSupportRequest(BaseModel):
    user_id: str
    profile: dict
    matches: list[dict]


class ApplicationSupportResponse(BaseModel):
    materials: list[dict]
