"""Pydantic models for workflow orchestration."""

from enum import Enum

from pydantic import BaseModel


class WorkflowState(str, Enum):
    """Sequential state machine for the scholarship-discovery workflow."""

    INITIATED = "INITIATED"
    PROFILE_PARSING = "PROFILE_PARSING"
    PROFILE_COMPLETE = "PROFILE_COMPLETE"
    DISCOVERING_PROGRAMS = "DISCOVERING_PROGRAMS"
    DISCOVERING_SCHOLARSHIPS = "DISCOVERING_SCHOLARSHIPS"
    MATCHING = "MATCHING"
    GENERATING_MATERIALS = "GENERATING_MATERIALS"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"


class WorkflowRunResponse(BaseModel):
    id: str
    chat_id: str
    user_id: str
    current_state: WorkflowState
    last_successful_state: WorkflowState | None
    error_message: str | None
    started_at: str
    completed_at: str | None


class WorkflowResultResponse(BaseModel):
    id: str
    workflow_run_id: str
    student_profile: dict | None = None
    programs: list | None = None
    scholarships: list | None = None
    eligibility_matches: list | None = None
    application_materials: list | None = None
