"""Tracked application endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.middleware.auth_middleware import get_current_user_id
from app.models.applications import (
    ApplicationActionResponse,
    TrackedApplicationCreate,
    TrackedApplicationResponse,
    TrackedApplicationUpdate,
)
from app.services.application_tracking_service import ApplicationTrackingService

router = APIRouter(prefix="/api/v1/applications", tags=["Applications"])


def _get_application_tracking_service() -> ApplicationTrackingService:
    return ApplicationTrackingService()


@router.get("", response_model=list[TrackedApplicationResponse])
async def list_applications(
    user_id: str = Depends(get_current_user_id),
    service: ApplicationTrackingService = Depends(_get_application_tracking_service),
):
    """List applications the current user explicitly started tracking."""
    return await service.list_applications(user_id=user_id)


@router.post("", response_model=TrackedApplicationResponse)
async def start_application(
    body: TrackedApplicationCreate,
    user_id: str = Depends(get_current_user_id),
    service: ApplicationTrackingService = Depends(_get_application_tracking_service),
):
    """Start tracking a program or scholarship application."""
    return await service.start_application(user_id=user_id, body=body)


@router.patch("/{application_id}", response_model=TrackedApplicationResponse)
async def update_application(
    application_id: str,
    body: TrackedApplicationUpdate,
    user_id: str = Depends(get_current_user_id),
    service: ApplicationTrackingService = Depends(_get_application_tracking_service),
):
    """Update tracked application status."""
    return await service.update_application(user_id=user_id, application_id=application_id, body=body)


@router.post("/{application_id}/checklist", response_model=ApplicationActionResponse)
async def create_checklist(
    application_id: str,
    user_id: str = Depends(get_current_user_id),
    service: ApplicationTrackingService = Depends(_get_application_tracking_service),
):
    """Create or refresh an application-support checklist for this tracked application."""
    return await service.create_checklist(user_id=user_id, application_id=application_id)


@router.post("/{application_id}/deadline-sync", response_model=ApplicationActionResponse)
async def sync_deadline(
    application_id: str,
    user_id: str = Depends(get_current_user_id),
    service: ApplicationTrackingService = Depends(_get_application_tracking_service),
):
    """Sync application deadlines for this tracked application."""
    return await service.sync_deadline(user_id=user_id, application_id=application_id)


@router.post("/{application_id}/generate-sop", response_model=ApplicationActionResponse)
async def generate_sop(
    application_id: str,
    user_id: str = Depends(get_current_user_id),
    service: ApplicationTrackingService = Depends(_get_application_tracking_service),
):
    """Generate a Statement of Purpose for this tracked application."""
    return await service.generate_sop(user_id=user_id, application_id=application_id)


@router.post("/{application_id}/generate-cover-letter", response_model=ApplicationActionResponse)
async def generate_cover_letter(
    application_id: str,
    user_id: str = Depends(get_current_user_id),
    service: ApplicationTrackingService = Depends(_get_application_tracking_service),
):
    """Generate a cover letter for this tracked application."""
    return await service.generate_cover_letter(user_id=user_id, application_id=application_id)
