"""Models for tracked applications started from discovery results."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ApplicationEntityType = Literal["program", "scholarship"]
ApplicationStatus = Literal["not_started", "in_progress", "applied", "accepted", "rejected"]


class TrackedApplicationCreate(BaseModel):
    """Start tracking an application from a discovery result."""

    entity_type: ApplicationEntityType = "program"
    entity_id: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=255)
    provider: Optional[str] = Field(default=None, max_length=255)
    match_score: Optional[float] = Field(default=None, ge=0, le=100)
    deadline: Optional[date] = None
    source_data: dict[str, Any] = Field(default_factory=dict)


class TrackedApplicationUpdate(BaseModel):
    """Update tracked application state."""

    status: ApplicationStatus


class TrackedApplicationResponse(BaseModel):
    """Tracked application returned to FE."""

    id: str
    user_id: str
    entity_type: ApplicationEntityType
    entity_id: str
    title: str
    provider: Optional[str] = None
    status: ApplicationStatus
    match_score: Optional[float] = None
    deadline: Optional[date] = None
    source_data: dict[str, Any] = Field(default_factory=dict)
    checklist_output: Optional[dict[str, Any]] = None
    deadline_output: Optional[dict[str, Any]] = None
    sop_output: Optional[dict[str, Any]] = None
    cover_letter_output: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ApplicationActionResponse(BaseModel):
    """Response for application-support actions tied to a tracked application."""

    application: TrackedApplicationResponse
    output: dict[str, Any]
