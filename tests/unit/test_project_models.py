"""Unit tests for project Pydantic models."""

import pytest
from pydantic import ValidationError

from app.models.project import CreateProjectRequest, UpdateProjectRequest


class TestCreateProjectRequest:
    """Tests for CreateProjectRequest model."""

    def test_valid_minimal(self):
        req = CreateProjectRequest(name="My Project")
        assert req.name == "My Project"
        assert req.description is None
        assert req.color is None
        assert req.icon is None

    def test_valid_full(self):
        req = CreateProjectRequest(
            name="My Project",
            description="A description",
            color="#3B82F6",
            icon="folder",
        )
        assert req.name == "My Project"
        assert req.description == "A description"
        assert req.color == "#3B82F6"
        assert req.icon == "folder"

    def test_name_whitespace_stripped(self):
        req = CreateProjectRequest(name="  My Project  ")
        assert req.name == "My Project"

    def test_empty_name_fails(self):
        with pytest.raises(ValidationError):
            CreateProjectRequest(name="")

    def test_whitespace_only_name_fails(self):
        with pytest.raises(ValidationError):
            CreateProjectRequest(name="   ")

    def test_name_too_long_fails(self):
        with pytest.raises(ValidationError):
            CreateProjectRequest(name="a" * 101)

    def test_invalid_color_format_fails(self):
        with pytest.raises(ValidationError):
            CreateProjectRequest(name="My Project", color="red")

    def test_invalid_color_short_hex_fails(self):
        with pytest.raises(ValidationError):
            CreateProjectRequest(name="My Project", color="#FFF")

    def test_invalid_color_no_hash_fails(self):
        with pytest.raises(ValidationError):
            CreateProjectRequest(name="My Project", color="3B82F6")

    def test_valid_lowercase_hex_color(self):
        req = CreateProjectRequest(name="My Project", color="#3b82f6")
        assert req.color == "#3b82f6"

    def test_icon_too_long_fails(self):
        with pytest.raises(ValidationError):
            CreateProjectRequest(name="My Project", icon="a" * 51)

    def test_description_too_long_fails(self):
        with pytest.raises(ValidationError):
            CreateProjectRequest(name="My Project", description="a" * 501)


class TestUpdateProjectRequest:
    """Tests for UpdateProjectRequest model."""

    def test_all_none(self):
        req = UpdateProjectRequest()
        assert req.name is None
        assert req.description is None
        assert req.color is None
        assert req.icon is None

    def test_partial_update_name(self):
        req = UpdateProjectRequest(name="New Name")
        assert req.name == "New Name"
        assert req.color is None

    def test_partial_update_color(self):
        req = UpdateProjectRequest(color="#10B981")
        assert req.color == "#10B981"
        assert req.name is None

    def test_name_whitespace_stripped(self):
        req = UpdateProjectRequest(name="  New Name  ")
        assert req.name == "New Name"

    def test_empty_name_fails(self):
        with pytest.raises(ValidationError):
            UpdateProjectRequest(name="")

    def test_whitespace_only_name_fails(self):
        with pytest.raises(ValidationError):
            UpdateProjectRequest(name="   ")

    def test_invalid_color_fails(self):
        with pytest.raises(ValidationError):
            UpdateProjectRequest(color="invalid")
