"""Pydantic request/response models for project management."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Request Models ───────────────────────────────────────────────────────────


class CreateProjectRequest(BaseModel):
    """Create a new project for organizing chats."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Project name",
        examples=["Singapore Scholarships"],
    )
    description: Optional[str] = Field(
        None,
        max_length=500,
        description="Optional project description",
        examples=["Research on scholarship opportunities in Singapore"],
    )
    color: Optional[str] = Field(
        None,
        pattern=r"^#[0-9A-Fa-f]{6}$",
        description="Hex color code for UI display",
        examples=["#3B82F6"],
    )
    icon: Optional[str] = Field(
        None,
        max_length=50,
        description="Icon identifier for UI",
        examples=["folder", "briefcase", "graduation-cap"],
    )

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Project name cannot be empty or whitespace only")
        return stripped


class UpdateProjectRequest(BaseModel):
    """Update project metadata."""

    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="New project name",
        examples=["My Research Projects"],
    )
    description: Optional[str] = Field(
        None,
        max_length=500,
        description="New project description",
    )
    color: Optional[str] = Field(
        None,
        pattern=r"^#[0-9A-Fa-f]{6}$",
        description="New hex color code",
        examples=["#10B981"],
    )
    icon: Optional[str] = Field(
        None,
        max_length=50,
        description="New icon identifier",
    )

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("Project name cannot be empty or whitespace only")
        return stripped


# ── Response Models ──────────────────────────────────────────────────────────


class ProjectResponse(BaseModel):
    """Project metadata."""

    id: str = Field(..., examples=["proj-a1b2c3d4-e5f6-7890-abcd-ef1234567890"])
    name: str = Field(..., examples=["Singapore Scholarships"])
    description: Optional[str] = Field(None, examples=["Research on Singapore opportunities"])
    color: Optional[str] = Field(None, examples=["#3B82F6"])
    icon: Optional[str] = Field(None, examples=["folder"])
    chat_count: int = Field(..., examples=[5])
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedProjectsResponse(BaseModel):
    """Paginated list of projects."""

    projects: list[ProjectResponse]
    next_cursor: Optional[str] = Field(
        None,
        description="Cursor for next page (base64-encoded updated_at timestamp)",
    )
    total_count: int = Field(..., description="Total projects for this user (excluding deleted)")
