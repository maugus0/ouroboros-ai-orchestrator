"""Unit tests for ApplicationTrackingService status transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services.application_tracking_service import ApplicationTrackingService


@dataclass
class _FakeApplicationRepo:
    app: dict[str, Any]
    last_update_outputs: dict[str, Any] | None = None

    async def get_by_id(self, *, user_id: str, application_id: str) -> dict[str, Any] | None:
        if self.app["user_id"] != user_id or self.app["id"] != application_id:
            return None
        return dict(self.app)

    async def update_outputs(self, **kwargs) -> dict[str, Any]:
        self.last_update_outputs = dict(kwargs)
        updated = dict(self.app)
        updated.update(
            {
                key: value
                for key, value in kwargs.items()
                if key in {"checklist_output", "deadline_output", "sop_output", "cover_letter_output", "status"}
            }
        )
        self.app = updated
        return dict(updated)


def _make_program_app(status: str = "not_started") -> dict[str, Any]:
    return {
        "id": "app-1",
        "user_id": "user-1",
        "entity_type": "program",
        "entity_id": "program-1",
        "title": "MSCS",
        "provider": "Imperial College London",
        "status": status,
        "source_data": {
            "program_name": "MSCS",
            "university": "Imperial College London",
            "match": {"match_score": 88.2},
        },
    }


@pytest.mark.asyncio
async def test_create_checklist_moves_not_started_application_to_in_progress():
    repo = _FakeApplicationRepo(app=_make_program_app(status="not_started"))
    client = AsyncMock()
    client.create_checklist.return_value = {"data": {"items": []}}

    service = ApplicationTrackingService(
        application_repo=repo,
        aggregated_repo=AsyncMock(),
        application_support_client=client,
    )

    response = await service.create_checklist(user_id="user-1", application_id="app-1")

    assert response["application"]["status"] == "in_progress"
    assert repo.last_update_outputs is not None
    assert repo.last_update_outputs["status"] == "in_progress"


@pytest.mark.asyncio
async def test_generate_cover_letter_preserves_applied_status():
    repo = _FakeApplicationRepo(app=_make_program_app(status="applied"))
    aggregated_repo = AsyncMock()
    aggregated_repo.get_latest_for_user.return_value = {
        "dashboard_view": {"profile": {"details": {"full_name": "Test User"}}}
    }
    client = AsyncMock()
    client.generate_cover_letter.return_value = {"data": {"content": "Cover letter"}}

    service = ApplicationTrackingService(
        application_repo=repo,
        aggregated_repo=aggregated_repo,
        application_support_client=client,
    )

    response = await service.generate_cover_letter(user_id="user-1", application_id="app-1")

    assert response["application"]["status"] == "applied"
    assert repo.last_update_outputs is not None
    assert repo.last_update_outputs["status"] == "applied"
