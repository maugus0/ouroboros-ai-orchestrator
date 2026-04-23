"""Request/response models for aggregated discovery results."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class DiscoverRequest(BaseModel):
    """Input filters for running discovery aggregation."""

    query: Optional[str] = Field(default=None, description="Optional free-text query hint.")
    target_field: Optional[str] = Field(default=None, description="Desired field of study.")
    target_degree: Optional[str] = Field(default=None, description="Desired degree level.")
    countries: list[str] = Field(default_factory=list, description="Preferred target countries.")
    max_tuition_usd: Optional[float] = Field(default=None, ge=0)
    limit: int = Field(default=10, ge=1, le=25)
    include_attribution: bool = Field(default=True)
    sync_application_deadlines: bool = Field(default=False)
    force_refresh: bool = Field(default=True)


class DashboardHistoryItem(BaseModel):
    """Small summary item for recent discovery runs."""

    workflow_id: str
    status: str
    version: int
    created_at: Optional[datetime] = None


class DiscoverResponse(BaseModel):
    """Response returned after triggering discovery pipeline."""

    workflow_id: str
    status: str
    version: int
    dashboard: dict[str, Any]


class AggregatedResultResponse(BaseModel):
    """Detailed per-workflow aggregate response."""

    workflow_id: str
    user_id: str
    status: str
    version: int
    is_latest: bool
    dashboard: dict[str, Any]
    raw_outputs: dict[str, Any]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    versions: Optional[list[dict[str, Any]]] = None


class DashboardResponse(BaseModel):
    """Latest dashboard aggregate for a user."""

    has_results: bool
    latest_workflow_id: Optional[str] = None
    dashboard: Optional[dict[str, Any]] = None
    history: list[DashboardHistoryItem] = Field(default_factory=list)
