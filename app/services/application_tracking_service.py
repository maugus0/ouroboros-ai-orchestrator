"""Application tracking orchestration."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Optional

from fastapi import HTTPException, status

from app.clients.agent_client import AgentClientError
from app.clients.application_support_client import ApplicationSupportClient
from app.core.database import get_pool
from app.models.applications import TrackedApplicationCreate, TrackedApplicationUpdate
from app.repositories.aggregated_result_repo import AggregatedResultRepository
from app.repositories.tracked_application_repo import TrackedApplicationRepository


def _lazy_application_repo() -> TrackedApplicationRepository:
    return TrackedApplicationRepository(get_pool())


def _lazy_aggregated_repo() -> AggregatedResultRepository:
    return AggregatedResultRepository(get_pool())


class ApplicationTrackingService:
    """Tracks user-started applications and delegates support tasks."""

    def __init__(
        self,
        *,
        application_repo: Optional[TrackedApplicationRepository] = None,
        aggregated_repo: Optional[AggregatedResultRepository] = None,
        application_support_client: Optional[ApplicationSupportClient] = None,
    ) -> None:
        self._application_repo = application_repo
        self._aggregated_repo = aggregated_repo
        self._application_support_client = application_support_client

    @property
    def application_repo(self) -> TrackedApplicationRepository:
        if self._application_repo is None:
            self._application_repo = _lazy_application_repo()
        return self._application_repo

    @property
    def aggregated_repo(self) -> AggregatedResultRepository:
        if self._aggregated_repo is None:
            self._aggregated_repo = _lazy_aggregated_repo()
        return self._aggregated_repo

    @property
    def application_support_client(self) -> ApplicationSupportClient:
        if self._application_support_client is None:
            self._application_support_client = ApplicationSupportClient()
        return self._application_support_client

    async def list_applications(self, *, user_id: str) -> list[dict[str, Any]]:
        return await self.application_repo.list_for_user(user_id=user_id)

    async def start_application(self, *, user_id: str, body: TrackedApplicationCreate) -> dict[str, Any]:
        app = await self.application_repo.create_or_get(
            row_id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            title=body.title,
            provider=body.provider,
            match_score=body.match_score,
            deadline=body.deadline,
            source_data=body.source_data,
        )

        checklist_output = await self._safe_create_checklist(user_id=user_id, app=app)
        deadline_output = await self._safe_sync_deadline(user_id=user_id, app=app)

        if checklist_output is not None or deadline_output is not None:
            app = await self.application_repo.update_outputs(
                user_id=user_id,
                application_id=app["id"],
                checklist_output=checklist_output,
                deadline_output=deadline_output,
            ) or app
        return app

    async def update_application(self, *, user_id: str, application_id: str, body: TrackedApplicationUpdate) -> dict[str, Any]:
        app = await self.application_repo.update_status(user_id=user_id, application_id=application_id, status=body.status)
        if app is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
        return app

    async def generate_sop(self, *, user_id: str, application_id: str) -> dict[str, Any]:
        app = await self._get_application_or_404(user_id=user_id, application_id=application_id)
        if app["entity_type"] != "program":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SOP generation is only available for program applications",
            )
        latest = await self.aggregated_repo.get_latest_for_user(user_id=user_id)
        dashboard = latest.get("dashboard_view") if isinstance(latest, dict) else {}
        profile = {}
        if isinstance(dashboard, dict) and isinstance(dashboard.get("profile"), dict):
            profile = dashboard["profile"].get("details") if isinstance(dashboard["profile"].get("details"), dict) else {}

        payload = {
            "user_id": user_id,
            "program_id": app["entity_id"] if app["entity_type"] == "program" else None,
            "user_profile": profile,
            "target_program": app.get("source_data") or {"program_name": app["title"], "university": app.get("provider")},
            "match_attribution": self._extract_match_attribution(app),
        }
        try:
            output = await self.application_support_client.generate_sop(user_id=user_id, payload=payload)
        except AgentClientError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

        updated = await self.application_repo.update_outputs(
            user_id=user_id,
            application_id=application_id,
            sop_output=output,
            status=self._status_after_support_action(app),
        )
        return {"application": updated or app, "output": output}

    async def generate_cover_letter(self, *, user_id: str, application_id: str) -> dict[str, Any]:
        app = await self._get_application_or_404(user_id=user_id, application_id=application_id)
        latest = await self.aggregated_repo.get_latest_for_user(user_id=user_id)
        dashboard = latest.get("dashboard_view") if isinstance(latest, dict) else {}
        profile = {}
        if isinstance(dashboard, dict) and isinstance(dashboard.get("profile"), dict):
            details = dashboard["profile"].get("details")
            profile = details if isinstance(details, dict) else {}

        payload = {
            "user_id": user_id,
            "target_type": app["entity_type"],
            "target_id": app["entity_id"],
            "user_profile": profile,
            "target_details": app.get("source_data") or {"name": app["title"], "provider": app.get("provider")},
        }
        try:
            output = await self.application_support_client.generate_cover_letter(user_id=user_id, payload=payload)
        except AgentClientError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

        updated = await self.application_repo.update_outputs(
            user_id=user_id,
            application_id=application_id,
            cover_letter_output=output,
            status=self._status_after_support_action(app),
        )
        return {"application": updated or app, "output": output}

    async def create_checklist(self, *, user_id: str, application_id: str) -> dict[str, Any]:
        app = await self._get_application_or_404(user_id=user_id, application_id=application_id)
        output = await self._create_checklist(user_id=user_id, app=app)
        updated = await self.application_repo.update_outputs(
            user_id=user_id,
            application_id=application_id,
            checklist_output=output,
            status=self._status_after_support_action(app),
        )
        return {"application": updated or app, "output": output}

    async def sync_deadline(self, *, user_id: str, application_id: str) -> dict[str, Any]:
        app = await self._get_application_or_404(user_id=user_id, application_id=application_id)
        output = await self._sync_deadline(user_id=user_id, app=app)
        updated = await self.application_repo.update_outputs(
            user_id=user_id,
            application_id=application_id,
            deadline_output=output,
            status=self._status_after_support_action(app),
        )
        return {"application": updated or app, "output": output}

    async def _get_application_or_404(self, *, user_id: str, application_id: str) -> dict[str, Any]:
        app = await self.application_repo.get_by_id(user_id=user_id, application_id=application_id)
        if app is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
        return app

    async def _safe_create_checklist(self, *, user_id: str, app: dict[str, Any]) -> Optional[dict[str, Any]]:
        try:
            return await self._create_checklist(user_id=user_id, app=app)
        except AgentClientError:
            return None

    async def _safe_sync_deadline(self, *, user_id: str, app: dict[str, Any]) -> Optional[dict[str, Any]]:
        try:
            return await self._sync_deadline(user_id=user_id, app=app)
        except AgentClientError:
            return None

    async def _create_checklist(self, *, user_id: str, app: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "user_id": user_id,
            "program_id": app["entity_id"] if app["entity_type"] == "program" else None,
            "items": [],
            "program_requirements": self._requirements_text(app.get("source_data")),
            "target_program": app.get("source_data") or {},
        }
        return await self.application_support_client.create_checklist(user_id=user_id, payload=payload)

    async def _sync_deadline(self, *, user_id: str, app: dict[str, Any]) -> dict[str, Any]:
        source = dict(app.get("source_data") or {})
        if app.get("deadline") and not source.get("deadline"):
            source["deadline"] = app["deadline"].isoformat() if isinstance(app["deadline"], date) else str(app["deadline"])
        payload = {
            "user_id": user_id,
            "programs": [source] if app["entity_type"] == "program" else [],
            "scholarships": [source] if app["entity_type"] == "scholarship" else [],
        }
        return await self.application_support_client.sync_deadlines(user_id=user_id, payload=payload)

    @staticmethod
    def _requirements_text(source_data: Any) -> Optional[str]:
        if not isinstance(source_data, dict):
            return None
        requirements = source_data.get("requirements")
        if isinstance(requirements, str):
            return requirements
        if isinstance(requirements, dict):
            return "; ".join(f"{key}: {value}" for key, value in requirements.items())
        return None

    @staticmethod
    def _extract_match_attribution(app: dict[str, Any]) -> dict[str, Any]:
        source = app.get("source_data")
        if isinstance(source, dict):
            match = source.get("match")
            if isinstance(match, dict):
                return match
        return {}

    @staticmethod
    def _status_after_support_action(app: dict[str, Any]) -> str:
        current_status = str(app.get("status") or "not_started")
        return "in_progress" if current_status == "not_started" else current_status
