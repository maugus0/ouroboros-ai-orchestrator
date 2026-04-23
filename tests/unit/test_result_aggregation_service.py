"""Unit tests for ResultAggregationService."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.clients.agent_client import AgentClientError
from app.models.results import DiscoverRequest
from app.services.result_aggregation_service import ResultAggregationService


@dataclass
class _FakeWorkflowRunRepo:
    created: list[dict[str, Any]] = field(default_factory=list)
    completed: list[dict[str, Any]] = field(default_factory=list)

    async def create_run(self, **kwargs):
        self.created.append(kwargs)

    async def complete_run(self, **kwargs):
        self.completed.append(kwargs)


@dataclass
class _FakeAggregatedRepo:
    rows: list[dict[str, Any]] = field(default_factory=list)

    async def get_next_version(self, workflow_run_id: str) -> int:
        versions = [int(r["result_version"]) for r in self.rows if r["workflow_run_id"] == workflow_run_id]
        return (max(versions) + 1) if versions else 1

    async def create_version(self, **kwargs):
        row = dict(kwargs)
        for existing in self.rows:
            if existing["workflow_run_id"] == row["workflow_run_id"]:
                existing["is_latest"] = False
        row["is_latest"] = True
        self.rows.append(row)

    async def get_latest_by_workflow(self, *, user_id: str, workflow_run_id: str):
        candidates = [r for r in self.rows if r["user_id"] == user_id and r["workflow_run_id"] == workflow_run_id]
        if not candidates:
            return None
        row = sorted(candidates, key=lambda r: int(r["result_version"]), reverse=True)[0]
        return self._normalize(row)

    async def get_latest_for_user(self, *, user_id: str):
        candidates = [r for r in self.rows if r["user_id"] == user_id and r.get("is_latest")]
        if not candidates:
            return None
        row = sorted(candidates, key=lambda r: int(r["result_version"]), reverse=True)[0]
        return self._normalize(row)

    async def list_latest_for_user(self, *, user_id: str, limit: int = 20):
        candidates = [self._normalize(r) for r in self.rows if r["user_id"] == user_id and r.get("is_latest")]
        return candidates[:limit]

    async def list_versions(self, *, user_id: str, workflow_run_id: str):
        candidates = [
            self._normalize(r) for r in self.rows if r["user_id"] == user_id and r["workflow_run_id"] == workflow_run_id
        ]
        return sorted(candidates, key=lambda r: int(r["result_version"]), reverse=True)

    @staticmethod
    def _normalize(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "workflow_run_id": row["workflow_run_id"],
            "user_id": row["user_id"],
            "result_version": row["result_version"],
            "is_latest": row.get("is_latest", True),
            "status": row["status"],
            "profile_output": row.get("profile_output"),
            "program_output": row.get("program_output"),
            "scholarship_output": row.get("scholarship_output"),
            "match_output": row.get("match_output"),
            "application_output": row.get("application_output"),
            "dashboard_view": row.get("dashboard_view"),
            "created_at": None,
            "updated_at": None,
        }


@dataclass
class _FakeAgentLogRepo:
    logs: list[dict[str, Any]] = field(default_factory=list)

    async def create_log(self, **kwargs):
        self.logs.append(kwargs)


class _StudentClient:
    async def get_profile_status(self, **_kwargs):
        return {"success": True, "data": {"profile_id": "profile-1", "completed": True, "missing_fields": []}}

    async def get_profile(self, profile_id: str, **_kwargs):
        return {
            "success": True,
            "data": {
                "id": profile_id,
                "gpa": "3.8",
                "gpa_scale": "4.0",
                "gpa_normalized": "3.8",
                "target_degree_level": "master",
                "intended_field_of_study": "Computer Science",
                "nationality": "Vietnam",
            },
        }


class _ProgramClient:
    def __init__(self) -> None:
        self.rank_calls: list[dict[str, Any]] = []

    async def rank_programs(self, **_kwargs):
        self.rank_calls.append(_kwargs)
        return [
            {
                "id": "program-1",
                "program_name": "MS Computer Science",
                "tuition_usd": "25000.00",
                "requirements": {"minimum_gpa": 3.5},
            }
        ]

    async def search_programs(self, **_kwargs):
        return {"items": []}


class _ScholarshipClient:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, Any]] = []

    async def search_scholarships(self, **_kwargs):
        self.search_calls.append(_kwargs)
        return {
            "success": True,
            "data": [{"id": "scholarship-1", "name": "NUS Merit", "eligibility_criteria": {"gpa": 3.5}}],
        }


class _EligibilityClient:
    def __init__(self) -> None:
        self.batch_calls: list[dict[str, Any]] = []

    async def evaluate_batch(self, **_kwargs):
        self.batch_calls.append(_kwargs)
        return {
            "success": True,
            "data": {
                "count": 2,
                "results": [
                    {
                        "match_result": {
                            "id": "m1",
                            "entity_type": "program",
                            "entity_id": "program-1",
                            "match_score": "88.2",
                        }
                    },
                    {
                        "match_result": {
                            "id": "m2",
                            "entity_type": "scholarship",
                            "entity_id": "scholarship-1",
                            "match_score": 84.5,
                        }
                    },
                ],
            },
        }


class _ProgramClientFailure(_ProgramClient):
    async def rank_programs(self, **_kwargs):
        raise AgentClientError(service_name="program-discovery", message="boom", status_code=503)


@pytest.mark.asyncio
async def test_discover_success_persists_versions_and_returns_dashboard():
    workflow_repo = _FakeWorkflowRunRepo()
    aggregate_repo = _FakeAggregatedRepo()
    log_repo = _FakeAgentLogRepo()
    program_client = _ProgramClient()
    scholarship_client = _ScholarshipClient()
    eligibility_client = _EligibilityClient()

    service = ResultAggregationService(
        workflow_run_repo=workflow_repo,
        aggregated_result_repo=aggregate_repo,
        agent_call_log_repo=log_repo,
        student_profile_client=_StudentClient(),
        program_discovery_client=program_client,
        scholarship_discovery_client=scholarship_client,
        eligibility_engine_client=eligibility_client,
    )

    payload = await service.discover(
        user_id="user-1",
        request=DiscoverRequest(target_field="Computer Science", target_degree="master", limit=5),
    )

    assert payload["status"] == "success"
    assert payload["dashboard"]["programs"]["total"] == 1
    assert payload["dashboard"]["scholarships"]["total"] == 1
    assert payload["dashboard"]["matches"]["total"] == 2
    assert payload["dashboard"]["programs"]["items"][0]["match"]["match_score"] == 88.2
    assert len(aggregate_repo.rows) >= 5
    assert workflow_repo.created
    assert workflow_repo.completed[-1]["status"] == "success"
    assert len(log_repo.logs) >= 3
    assert program_client.rank_calls[-1]["target_degree"] == "masters"
    assert scholarship_client.search_calls[-1]["payload"]["student_profile"]["degree_type"] == "master"
    assert eligibility_client.batch_calls[-1]["payload"]["user_profile"]["gpa_normalized"] == 3.8
    assert eligibility_client.batch_calls[-1]["payload"]["user_profile"]["gpa"] == 3.8
    assert eligibility_client.batch_calls[-1]["payload"]["user_profile"]["gpa_scale"] == 4.0
    program_eval = eligibility_client.batch_calls[-1]["payload"]["evaluations"][0]["entity_data"]
    assert program_eval["tuition_usd"] == 25000.0
    assert program_eval["minimum_gpa"] == 3.5


@pytest.mark.asyncio
async def test_discover_program_failure_returns_partial_status():
    workflow_repo = _FakeWorkflowRunRepo()
    aggregate_repo = _FakeAggregatedRepo()

    service = ResultAggregationService(
        workflow_run_repo=workflow_repo,
        aggregated_result_repo=aggregate_repo,
        agent_call_log_repo=_FakeAgentLogRepo(),
        student_profile_client=_StudentClient(),
        program_discovery_client=_ProgramClientFailure(),
        scholarship_discovery_client=_ScholarshipClient(),
        eligibility_engine_client=_EligibilityClient(),
    )

    payload = await service.discover(
        user_id="user-1",
        request=DiscoverRequest(target_field="Computer Science", target_degree="master", limit=5),
    )

    assert payload["status"] == "partial"
    assert payload["dashboard"]["errors"]
    assert workflow_repo.completed[-1]["workflow_state"] == "PARTIAL_SUCCESS"


@pytest.mark.asyncio
async def test_get_dashboard_empty_state_without_results():
    service = ResultAggregationService(
        workflow_run_repo=_FakeWorkflowRunRepo(),
        aggregated_result_repo=_FakeAggregatedRepo(),
        agent_call_log_repo=_FakeAgentLogRepo(),
        student_profile_client=_StudentClient(),
        program_discovery_client=_ProgramClient(),
        scholarship_discovery_client=_ScholarshipClient(),
        eligibility_engine_client=_EligibilityClient(),
    )

    dashboard = await service.get_dashboard(user_id="user-empty")
    assert dashboard["has_results"] is False
    assert dashboard["dashboard"] is None
    assert dashboard["history"] == []


@pytest.mark.asyncio
async def test_get_dashboard_history_after_discover_uses_persisted_rows():
    service = ResultAggregationService(
        workflow_run_repo=_FakeWorkflowRunRepo(),
        aggregated_result_repo=_FakeAggregatedRepo(),
        agent_call_log_repo=_FakeAgentLogRepo(),
        student_profile_client=_StudentClient(),
        program_discovery_client=_ProgramClient(),
        scholarship_discovery_client=_ScholarshipClient(),
        eligibility_engine_client=_EligibilityClient(),
    )

    await service.discover(user_id="user-1", request=DiscoverRequest(limit=5))
    await service.discover(user_id="user-1", request=DiscoverRequest(limit=5))

    dashboard = await service.get_dashboard(user_id="user-1", include_history=True)

    assert dashboard["has_results"] is True
    assert dashboard["history"]
    assert len(dashboard["history"]) == 2
