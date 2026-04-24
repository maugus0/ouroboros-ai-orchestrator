"""Request models for orchestrator-backed eligibility flows."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class EligibilityEvaluateRequest(BaseModel):
    """Request body accepted by the orchestrator for eligibility evaluation."""

    entity_type: Literal["program", "scholarship"] = Field(
        ...,
        description="Target entity type to evaluate against.",
        examples=["program"],
    )
    entity_id: str = Field(
        ...,
        description="Program or scholarship identifier known to the caller.",
        examples=["program-123"],
    )
    user_profile: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Structured student profile used for scoring. "
            "When omitted, the orchestrator hydrates it from student-profile."
        ),
    )
    entity_data: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Program or scholarship requirements/details for matching. "
            "When omitted, the orchestrator hydrates it from the downstream discovery service."
        ),
    )
    include_attribution: bool = Field(
        default=True,
        description="Whether to also generate explainability output.",
    )
