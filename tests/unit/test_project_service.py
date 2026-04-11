# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for ProjectService."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.project_service import ProjectService


@pytest.fixture
def mock_project_repo():
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.get_by_id_with_user = AsyncMock()
    repo.list_by_user = AsyncMock()
    repo.update = AsyncMock()
    repo.soft_delete = AsyncMock()
    repo.exists_for_user = AsyncMock()
    repo.increment_chat_count = AsyncMock()
    return repo


@pytest.fixture
def project_service(mock_project_repo):
    return ProjectService(project_repo=mock_project_repo)


@pytest.fixture
def sample_project():
    return {
        "id": "proj-123",
        "user_id": "user-456",
        "name": "Test Project",
        "description": "A test project",
        "color": "#3B82F6",
        "icon": "folder",
        "chat_count": 0,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "deleted_at": None,
    }


@pytest.mark.asyncio
async def test_create_project(project_service, mock_project_repo, sample_project):
    mock_project_repo.create.return_value = sample_project

    result = await project_service.create_project(
        user_id="user-456",
        name="Test Project",
        color="#3B82F6",
    )

    assert result["name"] == "Test Project"
    mock_project_repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_create_project_with_all_fields(project_service, mock_project_repo, sample_project):
    mock_project_repo.create.return_value = sample_project

    result = await project_service.create_project(
        user_id="user-456",
        name="Test Project",
        description="A test project",
        color="#3B82F6",
        icon="folder",
    )

    assert result["name"] == "Test Project"
    assert result["description"] == "A test project"
    mock_project_repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_get_project_success(project_service, mock_project_repo, sample_project):
    mock_project_repo.get_by_id_with_user.return_value = sample_project

    result = await project_service.get_project(user_id="user-456", project_id="proj-123")

    assert result["id"] == "proj-123"
    mock_project_repo.get_by_id_with_user.assert_called_once_with("proj-123")


@pytest.mark.asyncio
async def test_get_project_not_found(project_service, mock_project_repo):
    mock_project_repo.get_by_id_with_user.return_value = None

    with pytest.raises(Exception) as exc_info:
        await project_service.get_project(user_id="user-456", project_id="proj-123")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_project_not_owner(project_service, mock_project_repo, sample_project):
    mock_project_repo.get_by_id_with_user.return_value = {
        **sample_project,
        "user_id": "different-user",
    }

    with pytest.raises(Exception) as exc_info:
        await project_service.get_project(user_id="user-456", project_id="proj-123")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_project_deleted(project_service, mock_project_repo, sample_project):
    mock_project_repo.get_by_id_with_user.return_value = {
        **sample_project,
        "deleted_at": datetime.now(timezone.utc),
    }

    with pytest.raises(Exception) as exc_info:
        await project_service.get_project(user_id="user-456", project_id="proj-123")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_projects(project_service, mock_project_repo, sample_project):
    mock_project_repo.list_by_user.return_value = ([sample_project], 1)

    result = await project_service.list_projects(user_id="user-456")

    assert len(result["projects"]) == 1
    assert result["total_count"] == 1
    mock_project_repo.list_by_user.assert_called_once()


@pytest.mark.asyncio
async def test_list_projects_empty(project_service, mock_project_repo):
    mock_project_repo.list_by_user.return_value = ([], 0)

    result = await project_service.list_projects(user_id="user-456")

    assert len(result["projects"]) == 0
    assert result["total_count"] == 0
    assert result["next_cursor"] is None


@pytest.mark.asyncio
async def test_list_projects_with_pagination(project_service, mock_project_repo, sample_project):
    projects = [sample_project] * 20
    mock_project_repo.list_by_user.return_value = (projects, 50)

    result = await project_service.list_projects(user_id="user-456", limit=20)

    assert len(result["projects"]) == 20
    assert result["total_count"] == 50
    assert result["next_cursor"] is not None


@pytest.mark.asyncio
async def test_update_project(project_service, mock_project_repo, sample_project):
    mock_project_repo.get_by_id_with_user.return_value = sample_project
    mock_project_repo.update.return_value = {**sample_project, "name": "Updated Name"}

    result = await project_service.update_project(
        user_id="user-456",
        project_id="proj-123",
        name="Updated Name",
    )

    assert result["name"] == "Updated Name"
    mock_project_repo.update.assert_called_once()


@pytest.mark.asyncio
async def test_delete_project(project_service, mock_project_repo, sample_project):
    mock_project_repo.get_by_id_with_user.return_value = sample_project
    mock_project_repo.soft_delete.return_value = True

    await project_service.delete_project(user_id="user-456", project_id="proj-123")

    mock_project_repo.soft_delete.assert_called_once_with("proj-123")


@pytest.mark.asyncio
async def test_delete_project_not_found(project_service, mock_project_repo, sample_project):
    mock_project_repo.get_by_id_with_user.return_value = sample_project
    mock_project_repo.soft_delete.return_value = False

    with pytest.raises(Exception) as exc_info:
        await project_service.delete_project(user_id="user-456", project_id="proj-123")

    assert exc_info.value.status_code == 404
