"""Project management API endpoints."""

from typing import Optional

from fastapi import APIRouter, Body, Depends, Path, Query
from fastapi.openapi.models import Example

from app.middleware.auth_middleware import get_current_user_id
from app.models.project import (
    CreateProjectRequest,
    PaginatedProjectsResponse,
    ProjectResponse,
    UpdateProjectRequest,
)
from app.services.project_service import ProjectService

router = APIRouter(prefix="/api/v1/projects", tags=["Projects"])

# ── OpenAPI Examples ─────────────────────────────────────────────────────────

_CREATE_PROJECT_EXAMPLES: dict[str, Example] = {
    "scholarship_project": Example(
        summary="Create scholarship research project",
        description="Project with name, description, color, and icon for visual organization.",
        value={
            "name": "Singapore Scholarships",
            "description": "Research on scholarship opportunities in Singapore",
            "color": "#3B82F6",
            "icon": "graduation-cap",
        },
    ),
    "minimal_project": Example(
        summary="Create minimal project",
        description="Project with only required name field.",
        value={"name": "My Research"},
    ),
}

_UPDATE_PROJECT_EXAMPLES: dict[str, Example] = {
    "rename": Example(
        summary="Rename project",
        value={"name": "Graduate Programs Research"},
    ),
    "update_styling": Example(
        summary="Update color and icon",
        value={"color": "#10B981", "icon": "folder"},
    ),
    "full_update": Example(
        summary="Update all fields",
        value={
            "name": "Updated Project Name",
            "description": "New description for the project",
            "color": "#EF4444",
            "icon": "briefcase",
        },
    ),
}

# ── Response Examples ────────────────────────────────────────────────────────

_PROJECT_RESPONSE_EXAMPLE = {
    "id": "proj-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "name": "Singapore Scholarships",
    "description": "Research on scholarship opportunities in Singapore",
    "color": "#3B82F6",
    "icon": "graduation-cap",
    "chat_count": 5,
    "created_at": "2026-04-10T12:00:00Z",
    "updated_at": "2026-04-10T14:30:00Z",
}

_PAGINATED_PROJECTS_RESPONSE_EXAMPLE = {
    "projects": [
        {
            "id": "proj-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "name": "Singapore Scholarships",
            "description": "Research on Singapore opportunities",
            "color": "#3B82F6",
            "icon": "graduation-cap",
            "chat_count": 5,
            "created_at": "2026-04-10T12:00:00Z",
            "updated_at": "2026-04-10T14:30:00Z",
        },
        {
            "id": "proj-b2c3d4e5-f6a7-8901-bcde-f12345678901",
            "name": "US Graduate Programs",
            "description": None,
            "color": "#10B981",
            "icon": "folder",
            "chat_count": 3,
            "created_at": "2026-04-09T10:00:00Z",
            "updated_at": "2026-04-09T11:00:00Z",
        },
    ],
    "next_cursor": "MjAyNi0wNC0wOVQxMTowMDowMFo=",
    "total_count": 8,
}

# ── Service Instance ─────────────────────────────────────────────────────────

project_service = ProjectService()

# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=201,
    summary="Create a new project",
    responses={
        201: {
            "description": "Project created successfully",
            "content": {"application/json": {"example": _PROJECT_RESPONSE_EXAMPLE}},
        },
        401: {"description": "Missing or invalid Bearer token"},
        422: {"description": "Validation error (name empty or too long)"},
    },
)
async def create_project(
    body: CreateProjectRequest = Body(..., openapi_examples=_CREATE_PROJECT_EXAMPLES),
    user_id: str = Depends(get_current_user_id),
):
    """
    Create a new project for organizing chats.

    Projects are like folders that help you group related conversations.
    You can assign a color and icon for visual organization in the UI.
    """
    return await project_service.create_project(
        user_id=user_id,
        name=body.name,
        description=body.description,
        color=body.color,
        icon=body.icon,
    )


@router.get(
    "",
    response_model=PaginatedProjectsResponse,
    summary="List user's projects",
    responses={
        200: {
            "description": "Paginated list of projects ordered by updated_at descending",
            "content": {"application/json": {"example": _PAGINATED_PROJECTS_RESPONSE_EXAMPLE}},
        },
        401: {"description": "Missing or invalid Bearer token"},
    },
)
async def list_projects(
    limit: int = Query(50, ge=1, le=100, description="Number of projects to return"),
    cursor: Optional[str] = Query(None, description="Pagination cursor from previous response"),
    user_id: str = Depends(get_current_user_id),
):
    """
    List the authenticated user's projects.

    Projects are ordered by `updated_at` descending (most recently used first).
    Soft-deleted projects are excluded.
    """
    return await project_service.list_projects(
        user_id=user_id,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get a single project",
    responses={
        200: {
            "description": "Project details",
            "content": {"application/json": {"example": _PROJECT_RESPONSE_EXAMPLE}},
        },
        401: {"description": "Missing or invalid Bearer token"},
        404: {"description": "Project not found or belongs to another user"},
    },
)
async def get_project(
    project_id: str = Path(..., description="Project UUID"),
    user_id: str = Depends(get_current_user_id),
):
    """
    Get a single project by ID.

    Returns 404 if the project doesn't exist or belongs to another user.
    """
    return await project_service.get_project(user_id=user_id, project_id=project_id)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Update project",
    responses={
        200: {
            "description": "Project updated",
            "content": {"application/json": {"example": _PROJECT_RESPONSE_EXAMPLE}},
        },
        401: {"description": "Missing or invalid Bearer token"},
        404: {"description": "Project not found or belongs to another user"},
        422: {"description": "Validation error (name empty or too long)"},
    },
)
async def update_project(
    project_id: str = Path(..., description="Project UUID"),
    body: UpdateProjectRequest = Body(..., openapi_examples=_UPDATE_PROJECT_EXAMPLES),
    user_id: str = Depends(get_current_user_id),
):
    """
    Update project metadata.

    Only provided fields are updated; others remain unchanged.
    """
    return await project_service.update_project(
        user_id=user_id,
        project_id=project_id,
        name=body.name,
        description=body.description,
        color=body.color,
        icon=body.icon,
    )


@router.delete(
    "/{project_id}",
    status_code=204,
    summary="Delete a project",
    responses={
        204: {"description": "Project soft-deleted (no response body)"},
        401: {"description": "Missing or invalid Bearer token"},
        404: {"description": "Project not found or belongs to another user"},
    },
)
async def delete_project(
    project_id: str = Path(..., description="Project UUID"),
    user_id: str = Depends(get_current_user_id),
):
    """
    Soft-delete a project.

    The project is marked as deleted and excluded from list results.
    **Chats remain** but lose their project assignment (become unassigned).
    """
    await project_service.delete_project(user_id=user_id, project_id=project_id)
