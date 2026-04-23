"""Business logic for aggregated discovery result snapshots and dashboard reads."""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Optional

import aiomysql
from fastapi import HTTPException, status

from app.clients.agent_client import AgentClientError
from app.clients.application_support_client import ApplicationSupportClient
from app.clients.eligibility_engine_client import EligibilityEngineClient
from app.clients.program_discovery_client import ProgramDiscoveryClient
from app.clients.scholarship_discovery_client import ScholarshipDiscoveryClient
from app.clients.student_profile_client import StudentProfileClient
from app.core.database import get_pool
from app.core.logging import get_logger
from app.models.results import DiscoverRequest
from app.repositories.agent_call_log_repo import AgentCallLogRepository
from app.repositories.aggregated_result_repo import AggregatedResultRepository
from app.repositories.workflow_run_repo import WorkflowRunRepository

logger = get_logger(__name__)


def _lazy_workflow_run_repo() -> WorkflowRunRepository:
    return WorkflowRunRepository(get_pool())


def _lazy_aggregated_result_repo() -> AggregatedResultRepository:
    return AggregatedResultRepository(get_pool())


def _lazy_agent_call_log_repo() -> AgentCallLogRepository:
    return AgentCallLogRepository(get_pool())


def _lazy_student_profile_client() -> StudentProfileClient:
    return StudentProfileClient()


def _lazy_program_discovery_client() -> ProgramDiscoveryClient:
    return ProgramDiscoveryClient()


def _lazy_scholarship_discovery_client() -> ScholarshipDiscoveryClient:
    return ScholarshipDiscoveryClient()


def _lazy_eligibility_engine_client() -> EligibilityEngineClient:
    return EligibilityEngineClient()


def _lazy_application_support_client() -> ApplicationSupportClient:
    return ApplicationSupportClient()


class ResultAggregationService:
    """Coordinates multi-agent discovery and stores versioned aggregate snapshots."""

    _DASHBOARD_CACHE_TTL_SECONDS = 120
    _RESULT_CACHE_TTL_SECONDS = 300
    _CACHE_MAX_ENTRIES = 256
    _DASHBOARD_CACHE: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
    _RESULT_CACHE: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        workflow_run_repo: Optional[WorkflowRunRepository] = None,
        aggregated_result_repo: Optional[AggregatedResultRepository] = None,
        agent_call_log_repo: Optional[AgentCallLogRepository] = None,
        student_profile_client: Optional[StudentProfileClient] = None,
        program_discovery_client: Optional[ProgramDiscoveryClient] = None,
        scholarship_discovery_client: Optional[ScholarshipDiscoveryClient] = None,
        eligibility_engine_client: Optional[EligibilityEngineClient] = None,
        application_support_client: Optional[ApplicationSupportClient] = None,
    ) -> None:
        self._workflow_run_repo = workflow_run_repo
        self._aggregated_result_repo = aggregated_result_repo
        self._agent_call_log_repo = agent_call_log_repo
        self._student_profile_client = student_profile_client
        self._program_discovery_client = program_discovery_client
        self._scholarship_discovery_client = scholarship_discovery_client
        self._eligibility_engine_client = eligibility_engine_client
        self._application_support_client = application_support_client

    @property
    def workflow_run_repo(self) -> Optional[WorkflowRunRepository]:
        if self._workflow_run_repo is None:
            try:
                self._workflow_run_repo = _lazy_workflow_run_repo()
            except RuntimeError:
                return None
        return self._workflow_run_repo

    @property
    def aggregated_result_repo(self) -> Optional[AggregatedResultRepository]:
        if self._aggregated_result_repo is None:
            try:
                self._aggregated_result_repo = _lazy_aggregated_result_repo()
            except RuntimeError:
                return None
        return self._aggregated_result_repo

    @property
    def agent_call_log_repo(self) -> Optional[AgentCallLogRepository]:
        if self._agent_call_log_repo is None:
            try:
                self._agent_call_log_repo = _lazy_agent_call_log_repo()
            except RuntimeError:
                return None
        return self._agent_call_log_repo

    @property
    def student_profile_client(self) -> StudentProfileClient:
        if self._student_profile_client is None:
            self._student_profile_client = _lazy_student_profile_client()
        return self._student_profile_client

    @property
    def program_discovery_client(self) -> ProgramDiscoveryClient:
        if self._program_discovery_client is None:
            self._program_discovery_client = _lazy_program_discovery_client()
        return self._program_discovery_client

    @property
    def scholarship_discovery_client(self) -> ScholarshipDiscoveryClient:
        if self._scholarship_discovery_client is None:
            self._scholarship_discovery_client = _lazy_scholarship_discovery_client()
        return self._scholarship_discovery_client

    @property
    def eligibility_engine_client(self) -> EligibilityEngineClient:
        if self._eligibility_engine_client is None:
            self._eligibility_engine_client = _lazy_eligibility_engine_client()
        return self._eligibility_engine_client

    @property
    def application_support_client(self) -> ApplicationSupportClient:
        if self._application_support_client is None:
            self._application_support_client = _lazy_application_support_client()
        return self._application_support_client

    async def discover(
        self,
        *,
        user_id: str,
        request: DiscoverRequest,
        trace_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run the full discovery pipeline and persist versioned snapshots."""
        workflow_repo = self.workflow_run_repo
        aggregate_repo = self.aggregated_result_repo
        if workflow_repo is None or aggregate_repo is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

        workflow_id = str(uuid.uuid4())
        trace = trace_id or workflow_id
        session_id = workflow_id

        await workflow_repo.create_run(
            run_id=workflow_id,
            user_id=user_id,
            chat_id=None,
            workflow_type="result_aggregation_discovery",
            workflow_state="RECEIVED",
            context=request.model_dump(),
        )

        profile_output: Optional[dict[str, Any]] = None
        program_output: Optional[dict[str, Any]] = None
        scholarship_output: Optional[dict[str, Any]] = None
        match_output: Optional[dict[str, Any]] = None
        application_output: Optional[dict[str, Any]] = None
        errors: list[dict[str, Any]] = []
        agents: dict[str, dict[str, Any]] = {}
        final_status = "success"
        final_workflow_status = "success"
        final_workflow_state = "SUCCESS"

        try:
            profile_output, profile_meta = await self._call_student_profile(
                user_id=user_id,
                workflow_id=workflow_id,
                trace_id=trace,
                session_id=session_id,
                request=request,
            )
            agents["student-profile"] = profile_meta
            if profile_meta.get("status") == "failed":
                errors.append(self._to_error("student-profile", profile_meta.get("error", "Profile fetch failed")))
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Unable to load profile")

            await self._persist_snapshot(
                workflow_id=workflow_id,
                user_id=user_id,
                snapshot_status="in_progress",
                current_step="PROFILE_FETCH",
                profile_output=profile_output,
                program_output=program_output,
                scholarship_output=scholarship_output,
                match_output=match_output,
                application_output=application_output,
                agents=agents,
                errors=errors,
            )

            profile_data = self._extract_profile_data(profile_output)
            discovery_inputs = self._build_discovery_inputs(profile_data=profile_data, request=request)

            program_output, program_meta = await self._call_program_discovery(
                user_id=user_id,
                workflow_id=workflow_id,
                trace_id=trace,
                session_id=session_id,
                inputs=discovery_inputs,
            )
            agents["program-discovery"] = program_meta
            if program_meta.get("status") == "failed":
                final_status = "partial"
                errors.append(
                    self._to_error("program-discovery", program_meta.get("error", "Program discovery failed"))
                )
                program_output = {"error": program_meta.get("error"), "items": []}

            await self._persist_snapshot(
                workflow_id=workflow_id,
                user_id=user_id,
                snapshot_status="partial" if errors else "in_progress",
                current_step="PROGRAM_DISCOVERY",
                profile_output=profile_output,
                program_output=program_output,
                scholarship_output=scholarship_output,
                match_output=match_output,
                application_output=application_output,
                agents=agents,
                errors=errors,
            )

            scholarship_output, scholarship_meta = await self._call_scholarship_discovery(
                user_id=user_id,
                workflow_id=workflow_id,
                trace_id=trace,
                session_id=session_id,
                profile_data=profile_data,
                program_output=program_output,
                limit=discovery_inputs["limit"],
            )
            agents["scholarship-discovery"] = scholarship_meta
            if scholarship_meta.get("status") == "failed":
                final_status = "partial"
                errors.append(
                    self._to_error(
                        "scholarship-discovery", scholarship_meta.get("error", "Scholarship discovery failed")
                    )
                )
                scholarship_output = {"error": scholarship_meta.get("error"), "items": []}

            await self._persist_snapshot(
                workflow_id=workflow_id,
                user_id=user_id,
                snapshot_status="partial" if errors else "in_progress",
                current_step="SCHOLARSHIP_DISCOVERY",
                profile_output=profile_output,
                program_output=program_output,
                scholarship_output=scholarship_output,
                match_output=match_output,
                application_output=application_output,
                agents=agents,
                errors=errors,
            )

            match_output, match_meta = await self._call_eligibility_batch(
                user_id=user_id,
                workflow_id=workflow_id,
                trace_id=trace,
                session_id=session_id,
                profile_data=profile_data,
                program_output=program_output,
                scholarship_output=scholarship_output,
                include_attribution=bool(request.include_attribution),
            )
            agents["eligibility-engine"] = match_meta
            if match_meta.get("status") == "failed":
                final_status = "partial"
                errors.append(
                    self._to_error("eligibility-engine", match_meta.get("error", "Eligibility matching failed"))
                )
                match_output = {"error": match_meta.get("error"), "results": []}

            await self._persist_snapshot(
                workflow_id=workflow_id,
                user_id=user_id,
                snapshot_status="partial" if errors else "in_progress",
                current_step="ELIGIBILITY_MATCHING",
                profile_output=profile_output,
                program_output=program_output,
                scholarship_output=scholarship_output,
                match_output=match_output,
                application_output=application_output,
                agents=agents,
                errors=errors,
            )

            if request.sync_application_deadlines:
                application_output, app_meta = await self._call_application_deadline_sync(
                    user_id=user_id,
                    workflow_id=workflow_id,
                    trace_id=trace,
                    session_id=session_id,
                    program_output=program_output,
                    scholarship_output=scholarship_output,
                )
                agents["application-support"] = app_meta
                if app_meta.get("status") == "failed":
                    final_status = "partial"
                    errors.append(self._to_error("application-support", app_meta.get("error", "Deadline sync failed")))
                    application_output = {"error": app_meta.get("error")}

                await self._persist_snapshot(
                    workflow_id=workflow_id,
                    user_id=user_id,
                    snapshot_status="partial" if errors else "in_progress",
                    current_step="APPLICATION_SYNC",
                    profile_output=profile_output,
                    program_output=program_output,
                    scholarship_output=scholarship_output,
                    match_output=match_output,
                    application_output=application_output,
                    agents=agents,
                    errors=errors,
                )

        except HTTPException as exc:
            final_status = "failed"
            final_workflow_status = "failed"
            final_workflow_state = "FAILED_TERMINAL"
            if not errors:
                errors.append(self._to_error("orchestrator", str(exc.detail)))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            final_status = "failed"
            final_workflow_status = "failed"
            final_workflow_state = "FAILED_TERMINAL"
            errors.append(self._to_error("orchestrator", str(exc)))
            logger.error(
                "result_aggregation_unexpected_error", workflow_id=workflow_id, user_id=user_id, error=str(exc)
            )

        if final_status != "failed" and errors:
            final_status = "partial"
            final_workflow_status = "success"
            final_workflow_state = "PARTIAL_SUCCESS"
        if final_status == "success":
            final_workflow_status = "success"
            final_workflow_state = "SUCCESS"

        final_version = await self._persist_snapshot(
            workflow_id=workflow_id,
            user_id=user_id,
            snapshot_status=final_status,
            current_step="COMPLETED" if final_status != "failed" else "FAILED_TERMINAL",
            profile_output=profile_output,
            program_output=program_output,
            scholarship_output=scholarship_output,
            match_output=match_output,
            application_output=application_output,
            agents=agents,
            errors=errors,
            error_message=errors[0]["message"] if final_status == "failed" and errors else None,
        )

        await workflow_repo.complete_run(
            run_id=workflow_id,
            status=final_workflow_status,
            workflow_state=final_workflow_state,
            error_message=errors[0]["message"] if final_status == "failed" and errors else None,
            context={
                "status": final_status,
                "errors": errors,
                "agents": agents,
            },
        )

        dashboard = self._build_dashboard_view(
            workflow_id=workflow_id,
            version=final_version,
            result_status=final_status,
            profile_output=profile_output,
            program_output=program_output,
            scholarship_output=scholarship_output,
            match_output=match_output,
            application_output=application_output,
            agents=agents,
            errors=errors,
        )

        if final_status != "failed":
            self._invalidate_dashboard_cache(user_id)
            self._set_result_cache(
                user_id,
                workflow_id,
                self._to_result_payload(
                    workflow_id=workflow_id,
                    user_id=user_id,
                    result_status=final_status,
                    version=final_version,
                    is_latest=True,
                    dashboard=dashboard,
                    profile_output=profile_output,
                    program_output=program_output,
                    scholarship_output=scholarship_output,
                    match_output=match_output,
                    application_output=application_output,
                    created_at=None,
                    updated_at=None,
                    versions=None,
                ),
            )

        return {
            "workflow_id": workflow_id,
            "status": final_status,
            "version": final_version,
            "dashboard": dashboard,
        }

    async def get_workflow_result(
        self,
        *,
        user_id: str,
        workflow_id: str,
        include_versions: bool = False,
    ) -> Optional[dict[str, Any]]:
        """Fetch latest aggregate result for a workflow owned by user."""
        cached = self._get_result_cache(user_id, workflow_id)
        if cached is not None and not include_versions:
            return cached

        repo = self.aggregated_result_repo
        if repo is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

        latest = await repo.get_latest_by_workflow(user_id=user_id, workflow_run_id=workflow_id)
        if latest is None:
            return None

        versions = await repo.list_versions(user_id=user_id, workflow_run_id=workflow_id) if include_versions else None

        dashboard = latest.get("dashboard_view") if isinstance(latest.get("dashboard_view"), dict) else {}
        payload = self._to_result_payload(
            workflow_id=workflow_id,
            user_id=user_id,
            result_status=str(latest.get("status") or "failed"),
            version=int(latest.get("result_version") or 1),
            is_latest=bool(latest.get("is_latest")),
            dashboard=dashboard,
            profile_output=latest.get("profile_output"),
            program_output=latest.get("program_output"),
            scholarship_output=latest.get("scholarship_output"),
            match_output=latest.get("match_output"),
            application_output=latest.get("application_output"),
            created_at=latest.get("created_at"),
            updated_at=latest.get("updated_at"),
            versions=versions,
        )

        if not include_versions:
            self._set_result_cache(user_id, workflow_id, payload)
        return payload

    async def get_dashboard(
        self,
        *,
        user_id: str,
        include_history: bool = True,
        history_limit: int = 10,
    ) -> dict[str, Any]:
        """Return latest dashboard aggregate for user."""
        cached = self._get_dashboard_cache(user_id)
        if cached is not None:
            if not include_history or "history" in cached:
                return cached

        repo = self.aggregated_result_repo
        if repo is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

        latest = await repo.get_latest_for_user(user_id=user_id)
        if latest is None:
            response = {
                "has_results": False,
                "latest_workflow_id": None,
                "dashboard": None,
                "history": [],
            }
            self._set_dashboard_cache(user_id, response)
            return response

        history_items: list[dict[str, Any]] = []
        if include_history:
            history = await repo.list_latest_for_user(user_id=user_id, limit=history_limit)
            for row in history:
                history_items.append(
                    {
                        "workflow_id": row.get("workflow_run_id"),
                        "status": row.get("status"),
                        "version": int(row.get("result_version") or 1),
                        "created_at": row.get("created_at"),
                    }
                )

        response = {
            "has_results": True,
            "latest_workflow_id": latest.get("workflow_run_id"),
            "dashboard": latest.get("dashboard_view"),
            "history": history_items,
        }
        self._set_dashboard_cache(user_id, response)
        return response

    async def _call_student_profile(
        self,
        *,
        user_id: str,
        workflow_id: str,
        trace_id: str,
        session_id: str,
        request: DiscoverRequest,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        started_at = time.perf_counter()
        try:
            status_payload = await self.student_profile_client.get_profile_status(
                user_id=user_id,
                intent="program_discovery",
                trace_id=trace_id,
                session_id=session_id,
            )
            status_data = self._extract_data(status_payload)
            profile_payload = None
            profile_id = status_data.get("profile_id") if isinstance(status_data, dict) else None
            if isinstance(profile_id, str) and profile_id:
                profile_payload = await self.student_profile_client.get_profile(
                    profile_id=profile_id,
                    user_id=user_id,
                    trace_id=trace_id,
                    session_id=session_id,
                )
            output = {"status": status_payload, "profile": profile_payload, "request": request.model_dump()}
            latency_ms = self._elapsed_ms(started_at)
            await self._record_agent_call(
                workflow_id=workflow_id,
                user_id=user_id,
                target_service="student-profile",
                operation="aggregate_profile_fetch",
                request_method="GET",
                request_path="/api/v1/profiles/status",
                call_status="success",
                response_payload=self._truncate_payload(output),
                latency_ms=latency_ms,
            )
            return output, {"status": "success", "latency_ms": latency_ms, "operation": "aggregate_profile_fetch"}
        except AgentClientError as exc:
            latency_ms = self._elapsed_ms(started_at)
            await self._record_agent_call(
                workflow_id=workflow_id,
                user_id=user_id,
                target_service="student-profile",
                operation="aggregate_profile_fetch",
                request_method="GET",
                request_path="/api/v1/profiles/status",
                call_status="failed",
                http_status=exc.status_code,
                error_code="agent_client_error",
                error_message=str(exc),
                latency_ms=latency_ms,
            )
            return {}, {"status": "failed", "latency_ms": latency_ms, "error": "Unable to fetch profile"}

    async def _call_program_discovery(
        self,
        *,
        user_id: str,
        workflow_id: str,
        trace_id: str,
        session_id: str,
        inputs: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        started_at = time.perf_counter()
        try:
            op = "search_programs"
            path = "/programs"

            payload: Any
            if inputs.get("target_field"):
                payload = await self.program_discovery_client.rank_programs(
                    student_profile=inputs["student_profile"],
                    target_field=str(inputs["target_field"]),
                    target_degree=inputs.get("target_degree"),
                    country_preferences=inputs.get("countries"),
                    max_tuition_usd=inputs.get("max_tuition_usd"),
                    limit=int(inputs["limit"]),
                    user_id=user_id,
                    trace_id=trace_id,
                    session_id=session_id,
                )
                op = "rank_programs"
                path = "/programs/rank"
            else:
                payload = await self.program_discovery_client.search_programs(
                    field=None,
                    degree_type=inputs.get("target_degree"),
                    country=(inputs.get("countries") or [None])[0],
                    page=1,
                    page_size=int(inputs["limit"]),
                    user_id=user_id,
                    trace_id=trace_id,
                    session_id=session_id,
                )
                op = "search_programs"
                path = "/programs"

            latency_ms = self._elapsed_ms(started_at)
            await self._record_agent_call(
                workflow_id=workflow_id,
                user_id=user_id,
                target_service="program-discovery",
                operation=op,
                request_method="POST" if op == "rank_programs" else "GET",
                request_path=path,
                call_status="success",
                response_payload=self._truncate_payload(payload),
                latency_ms=latency_ms,
            )
            return payload if isinstance(payload, dict) else {"data": payload}, {
                "status": "success",
                "latency_ms": latency_ms,
                "operation": op,
                "count": len(self._extract_program_items(payload)),
            }
        except AgentClientError as exc:
            latency_ms = self._elapsed_ms(started_at)
            await self._record_agent_call(
                workflow_id=workflow_id,
                user_id=user_id,
                target_service="program-discovery",
                operation="aggregate_program_discovery",
                request_method="POST",
                request_path="/programs/rank",
                call_status="failed",
                http_status=exc.status_code,
                error_code="agent_client_error",
                error_message=str(exc),
                latency_ms=latency_ms,
            )
            return {}, {"status": "failed", "latency_ms": latency_ms, "error": "Program discovery unavailable"}

    async def _call_scholarship_discovery(
        self,
        *,
        user_id: str,
        workflow_id: str,
        trace_id: str,
        session_id: str,
        profile_data: dict[str, Any],
        program_output: Optional[dict[str, Any]],
        limit: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        started_at = time.perf_counter()
        student_profile = self._build_scholarship_profile_filter(profile_data)
        program_ids = [
            str(item.get("id"))
            for item in self._extract_program_items(program_output)
            if isinstance(item, dict) and item.get("id") is not None
        ]
        payload = {
            "student_profile": student_profile,
            "program_ids": program_ids,
            "max_results": limit,
            "page": 1,
        }
        try:
            result = await self.scholarship_discovery_client.search_scholarships(
                user_id=user_id,
                student_profile=student_profile,
                program_ids=program_ids if program_ids else None,
                max_results=limit,
                page=1,
                trace_id=trace_id,
                session_id=session_id,
            )
            latency_ms = self._elapsed_ms(started_at)
            await self._record_agent_call(
                workflow_id=workflow_id,
                user_id=user_id,
                target_service="scholarship-discovery",
                operation="search_scholarships",
                request_method="POST",
                request_path="/api/v1/scholarships/search",
                call_status="success",
                request_payload=self._truncate_payload(payload),
                response_payload=self._truncate_payload(result),
                latency_ms=latency_ms,
            )
            return result if isinstance(result, dict) else {"data": result}, {
                "status": "success",
                "latency_ms": latency_ms,
                "operation": "search_scholarships",
                "count": len(self._extract_scholarship_items(result)),
            }
        except AgentClientError as exc:
            latency_ms = self._elapsed_ms(started_at)
            await self._record_agent_call(
                workflow_id=workflow_id,
                user_id=user_id,
                target_service="scholarship-discovery",
                operation="search_scholarships",
                request_method="POST",
                request_path="/api/v1/scholarships/search",
                call_status="failed",
                http_status=exc.status_code,
                error_code="agent_client_error",
                error_message=str(exc),
                request_payload=self._truncate_payload(payload),
                latency_ms=latency_ms,
            )
            return {}, {"status": "failed", "latency_ms": latency_ms, "error": "Scholarship discovery unavailable"}

    async def _call_eligibility_batch(
        self,
        *,
        user_id: str,
        workflow_id: str,
        trace_id: str,
        session_id: str,
        profile_data: dict[str, Any],
        program_output: Optional[dict[str, Any]],
        scholarship_output: Optional[dict[str, Any]],
        include_attribution: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        started_at = time.perf_counter()
        evaluations = self._build_evaluations(program_output=program_output, scholarship_output=scholarship_output)
        if not evaluations:
            return {"data": {"count": 0, "results": []}}, {
                "status": "success",
                "latency_ms": 0,
                "operation": "evaluate_batch",
                "count": 0,
            }

        payload = {
            "user_id": user_id,
            "user_profile": self._build_matching_profile(profile_data),
            "evaluations": evaluations,
            "include_attribution": include_attribution,
        }
        try:
            result = await self.eligibility_engine_client.evaluate_batch(
                user_id=user_id,
                payload=payload,
                trace_id=trace_id,
                session_id=session_id,
            )
            latency_ms = self._elapsed_ms(started_at)
            await self._record_agent_call(
                workflow_id=workflow_id,
                user_id=user_id,
                target_service="eligibility-engine",
                operation="evaluate_batch",
                request_method="POST",
                request_path="/api/v1/eligibility/evaluate/batch",
                call_status="success",
                request_payload=self._truncate_payload(
                    {
                        "user_id": user_id,
                        "evaluation_count": len(evaluations),
                        "include_attribution": include_attribution,
                    }
                ),
                response_payload=self._truncate_payload(result),
                latency_ms=latency_ms,
            )
            return result if isinstance(result, dict) else {"data": result}, {
                "status": "success",
                "latency_ms": latency_ms,
                "operation": "evaluate_batch",
                "count": len(self._extract_match_results(result)),
            }
        except AgentClientError as exc:
            latency_ms = self._elapsed_ms(started_at)
            await self._record_agent_call(
                workflow_id=workflow_id,
                user_id=user_id,
                target_service="eligibility-engine",
                operation="evaluate_batch",
                request_method="POST",
                request_path="/api/v1/eligibility/evaluate/batch",
                call_status="failed",
                http_status=exc.status_code,
                error_code="agent_client_error",
                error_message=str(exc),
                latency_ms=latency_ms,
            )
            return {}, {"status": "failed", "latency_ms": latency_ms, "error": "Eligibility engine unavailable"}

    async def _call_application_deadline_sync(
        self,
        *,
        user_id: str,
        workflow_id: str,
        trace_id: str,
        session_id: str,
        program_output: Optional[dict[str, Any]],
        scholarship_output: Optional[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        started_at = time.perf_counter()
        payload = {
            "user_id": user_id,
            "programs": self._extract_program_items(program_output),
            "scholarships": self._extract_scholarship_items(scholarship_output),
        }
        try:
            result = await self.application_support_client.sync_deadlines(
                user_id=user_id,
                payload=payload,
                trace_id=trace_id,
                session_id=session_id,
            )
            latency_ms = self._elapsed_ms(started_at)
            await self._record_agent_call(
                workflow_id=workflow_id,
                user_id=user_id,
                target_service="application-support",
                operation="sync_deadlines",
                request_method="POST",
                request_path="/api/v1/applications/deadlines/sync",
                call_status="success",
                request_payload=self._truncate_payload(
                    {"program_count": len(payload["programs"]), "scholarship_count": len(payload["scholarships"])}
                ),
                response_payload=self._truncate_payload(result),
                latency_ms=latency_ms,
            )
            return result if isinstance(result, dict) else {"data": result}, {
                "status": "success",
                "latency_ms": latency_ms,
                "operation": "sync_deadlines",
            }
        except AgentClientError as exc:
            latency_ms = self._elapsed_ms(started_at)
            await self._record_agent_call(
                workflow_id=workflow_id,
                user_id=user_id,
                target_service="application-support",
                operation="sync_deadlines",
                request_method="POST",
                request_path="/api/v1/applications/deadlines/sync",
                call_status="failed",
                http_status=exc.status_code,
                error_code="agent_client_error",
                error_message=str(exc),
                latency_ms=latency_ms,
            )
            return {}, {"status": "failed", "latency_ms": latency_ms, "error": "Application deadline sync unavailable"}

    async def _persist_snapshot(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        *,
        workflow_id: str,
        user_id: str,
        snapshot_status: str,
        current_step: str,
        profile_output: Optional[dict[str, Any]],
        program_output: Optional[dict[str, Any]],
        scholarship_output: Optional[dict[str, Any]],
        match_output: Optional[dict[str, Any]],
        application_output: Optional[dict[str, Any]],
        agents: dict[str, dict[str, Any]],
        errors: list[dict[str, Any]],
        error_message: Optional[str] = None,
    ) -> int:
        repo = self.aggregated_result_repo
        if repo is None:
            return 1

        version = await repo.get_next_version(workflow_run_id=workflow_id)
        dashboard = self._build_dashboard_view(
            workflow_id=workflow_id,
            version=version,
            result_status=snapshot_status,
            profile_output=profile_output,
            program_output=program_output,
            scholarship_output=scholarship_output,
            match_output=match_output,
            application_output=application_output,
            agents=agents,
            errors=errors,
        )

        await repo.create_version(
            row_id=str(uuid.uuid4()),
            workflow_run_id=workflow_id,
            user_id=user_id,
            result_version=version,
            status=snapshot_status,
            current_step=current_step,
            profile_output=profile_output,
            program_output=program_output,
            scholarship_output=scholarship_output,
            match_output=match_output,
            application_output=application_output,
            dashboard_view=dashboard,
            error_message=error_message,
        )

        self._invalidate_dashboard_cache(user_id)
        self._invalidate_result_cache(user_id, workflow_id)
        return version

    async def _record_agent_call(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        *,
        workflow_id: str,
        user_id: str,
        target_service: str,
        operation: str,
        request_method: Optional[str],
        request_path: Optional[str],
        call_status: str,
        http_status: Optional[int] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        request_payload: Optional[dict[str, Any]] = None,
        response_payload: Optional[dict[str, Any]] = None,
        latency_ms: Optional[int] = None,
    ) -> None:
        repo = self.agent_call_log_repo
        if repo is None:
            return
        try:
            await repo.create_log(
                log_id=str(uuid.uuid4()),
                workflow_run_id=workflow_id,
                user_id=user_id,
                chat_id=None,
                target_service=target_service,
                operation=operation,
                request_method=request_method,
                request_path=request_path,
                attempt_number=1,
                status=call_status,
                http_status=http_status,
                error_code=error_code,
                error_message=error_message,
                request_payload=request_payload,
                response_payload=response_payload,
                trace_id=workflow_id,
                session_id=workflow_id,
                latency_ms=latency_ms,
                retry_of_log_id=None,
            )
        except (aiomysql.Error, RuntimeError, ValueError, TypeError, AttributeError) as exc:
            logger.warning(
                "aggregated_agent_log_write_failed", target_service=target_service, operation=operation, error=str(exc)
            )

    def _extract_profile_data(self, profile_output: Optional[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(profile_output, dict):
            return {}
        status_payload = self._extract_data(profile_output.get("status"))
        profile_payload = self._extract_data(profile_output.get("profile"))

        result: dict[str, Any] = {}
        if isinstance(status_payload, dict):
            result.update(status_payload)
        if isinstance(profile_payload, dict):
            result.update(profile_payload)
            profile_json = profile_payload.get("profile_json")
            if isinstance(profile_json, dict):
                result.update({k: v for k, v in profile_json.items() if k not in result})
        return result

    def _build_discovery_inputs(self, *, profile_data: dict[str, Any], request: DiscoverRequest) -> dict[str, Any]:
        countries = list(request.countries or [])
        if not countries:
            inferred_country = self._first_non_empty(
                profile_data.get("target_study_country"),
                profile_data.get("target_country"),
                profile_data.get("country"),
            )
            if isinstance(inferred_country, str) and inferred_country:
                countries = [inferred_country]

        target_degree = self._first_non_empty(
            request.target_degree,
            profile_data.get("target_degree_level"),
            profile_data.get("current_degree_level"),
            profile_data.get("degree_type"),
        )
        target_field = self._first_non_empty(
            request.target_field,
            profile_data.get("intended_field_of_study"),
            profile_data.get("field_of_study"),
            profile_data.get("target_field"),
        )

        limit = min(max(1, int(request.limit)), 25)
        student_profile = self._build_program_ranking_profile(profile_data)
        return {
            "target_field": target_field,
            "target_degree": self._normalize_program_degree(target_degree),
            "countries": countries,
            "max_tuition_usd": request.max_tuition_usd,
            "limit": limit,
            "student_profile": student_profile,
        }

    @staticmethod
    def _build_program_ranking_profile(profile_data: dict[str, Any]) -> dict[str, Any]:
        profile: dict[str, Any] = {}
        for key in (
            "gpa",
            "gpa_scale",
            "gpa_normalized",
            "nationality",
            "current_degree_level",
            "target_degree_level",
            "intended_field_of_study",
            "field_of_study",
            "funding_source",
            "enrollment_timeline",
        ):
            if profile_data.get(key) is not None:
                profile[key] = profile_data.get(key)
        return profile

    @staticmethod
    def _build_scholarship_profile_filter(profile_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "gpa": profile_data.get("gpa"),
            "gpa_scale": profile_data.get("gpa_scale") or 4.0,
            "nationality": profile_data.get("nationality"),
            "field_of_study": profile_data.get("intended_field_of_study") or profile_data.get("field_of_study"),
            "degree_type": ResultAggregationService._normalize_scholarship_degree(
                profile_data.get("target_degree_level") or profile_data.get("degree_type")
            ),
        }

    @classmethod
    def _build_matching_profile(cls, profile_data: dict[str, Any]) -> dict[str, Any]:
        gpa = cls._coerce_float(profile_data.get("gpa"))
        gpa_scale = cls._coerce_float(profile_data.get("gpa_scale")) or 4.0
        gpa_normalized = cls._coerce_float(profile_data.get("gpa_normalized"))
        if gpa_normalized is None and gpa is not None:
            try:
                gpa_normalized = (gpa / gpa_scale) * 4.0
            except (TypeError, ValueError, ZeroDivisionError):
                gpa_normalized = None

        return {
            "gpa": gpa,
            "gpa_scale": gpa_scale,
            "gpa_normalized": gpa_normalized,
            "nationality": profile_data.get("nationality"),
            "field_of_study": profile_data.get("intended_field_of_study") or profile_data.get("field_of_study"),
            "degree_type": profile_data.get("target_degree_level") or profile_data.get("degree_type"),
            "funding_source": profile_data.get("funding_source"),
            "enrollment_timeline": profile_data.get("enrollment_timeline"),
        }

    def _build_evaluations(
        self,
        *,
        program_output: Optional[dict[str, Any]],
        scholarship_output: Optional[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        evaluations: list[dict[str, Any]] = []
        for item in self._extract_program_items(program_output):
            if not isinstance(item, dict):
                continue
            entity_id = item.get("id")
            if entity_id is None:
                continue
            evaluations.append(
                {
                    "entity_type": "program",
                    "entity_id": str(entity_id),
                    "entity_data": self._build_program_match_data(item),
                }
            )
        for item in self._extract_scholarship_items(scholarship_output):
            if not isinstance(item, dict):
                continue
            entity_id = item.get("id")
            if entity_id is None:
                continue
            evaluations.append(
                {
                    "entity_type": "scholarship",
                    "entity_id": str(entity_id),
                    "entity_data": self._build_scholarship_match_data(item),
                }
            )
        return evaluations

    @classmethod
    def _build_program_match_data(cls, item: dict[str, Any]) -> dict[str, Any]:
        data = dict(item)
        for key in ("tuition_usd", "tuition_local", "minimum_gpa"):
            coerced = cls._coerce_float(data.get(key))
            if coerced is not None:
                data[key] = coerced

        requirements = data.get("requirements")
        if isinstance(requirements, dict) and data.get("minimum_gpa") is None:
            minimum_gpa = cls._coerce_float(requirements.get("minimum_gpa"))
            if minimum_gpa is not None:
                data["minimum_gpa"] = minimum_gpa

        return data

    @classmethod
    def _build_scholarship_match_data(cls, item: dict[str, Any]) -> dict[str, Any]:
        data = dict(item)
        for key in ("funding_amount", "minimum_gpa"):
            coerced = cls._coerce_float(data.get(key))
            if coerced is not None:
                data[key] = coerced
        return data

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _build_dashboard_view(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        *,
        workflow_id: str,
        version: int,
        result_status: str,
        profile_output: Optional[dict[str, Any]],
        program_output: Optional[dict[str, Any]],
        scholarship_output: Optional[dict[str, Any]],
        match_output: Optional[dict[str, Any]],
        application_output: Optional[dict[str, Any]],
        agents: dict[str, dict[str, Any]],
        errors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        match_items = self._extract_match_results(match_output)
        match_by_entity: dict[tuple[str, str], dict[str, Any]] = {}
        for item in match_items:
            if not isinstance(item, dict):
                continue
            entity_type, entity_id = self._extract_match_entity(item)
            if entity_type and entity_id:
                match_by_entity[(entity_type, entity_id)] = item

        programs: list[dict[str, Any]] = []
        for item in self._extract_program_items(program_output):
            if not isinstance(item, dict):
                continue
            enriched = dict(item)
            entity_id = str(item.get("id")) if item.get("id") is not None else None
            if entity_id:
                match_item = match_by_entity.get(("program", entity_id))
                if match_item:
                    enriched["match"] = self._normalize_match_summary(match_item)
            programs.append(enriched)

        scholarships: list[dict[str, Any]] = []
        for item in self._extract_scholarship_items(scholarship_output):
            if not isinstance(item, dict):
                continue
            enriched = dict(item)
            entity_id = str(item.get("id")) if item.get("id") is not None else None
            if entity_id:
                match_item = match_by_entity.get(("scholarship", entity_id))
                if match_item:
                    enriched["match"] = self._normalize_match_summary(match_item)
            scholarships.append(enriched)

        profile_data = self._extract_profile_data(profile_output)
        profile_status = (
            self._extract_data((profile_output or {}).get("status")) if isinstance(profile_output, dict) else {}
        )
        dashboard = {
            "workflow_id": workflow_id,
            "status": result_status,
            "version": version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "profile": {
                "status": profile_status if isinstance(profile_status, dict) else {},
                "details": profile_data,
            },
            "programs": {
                "items": programs,
                "total": len(programs),
            },
            "scholarships": {
                "items": scholarships,
                "total": len(scholarships),
            },
            "matches": {
                "items": match_items,
                "total": len(match_items),
            },
            "application": (
                self._extract_data(application_output) if isinstance(application_output, dict) else application_output
            ),
            "agents": agents,
            "errors": errors,
        }
        return dashboard

    def _to_result_payload(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        *,
        workflow_id: str,
        user_id: str,
        result_status: str,
        version: int,
        is_latest: bool,
        dashboard: dict[str, Any],
        profile_output: Any,
        program_output: Any,
        scholarship_output: Any,
        match_output: Any,
        application_output: Any,
        created_at: Any,
        updated_at: Any,
        versions: Optional[list[dict[str, Any]]],
    ) -> dict[str, Any]:
        return {
            "workflow_id": workflow_id,
            "user_id": user_id,
            "status": result_status,
            "version": version,
            "is_latest": is_latest,
            "dashboard": dashboard,
            "raw_outputs": {
                "profile": profile_output,
                "programs": program_output,
                "scholarships": scholarship_output,
                "matches": match_output,
                "application": application_output,
            },
            "created_at": created_at,
            "updated_at": updated_at,
            "versions": versions,
        }

    @staticmethod
    def _extract_data(payload: Any) -> Any:
        if isinstance(payload, dict) and "data" in payload and payload.get("data") is not None:
            return payload.get("data")
        return payload

    def _extract_program_items(self, payload: Any) -> list[dict[str, Any]]:
        data = self._extract_data(payload)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            if isinstance(data.get("items"), list):
                return [item for item in data.get("items", []) if isinstance(item, dict)]
            if isinstance(data.get("programs"), list):
                return [item for item in data.get("programs", []) if isinstance(item, dict)]
        return []

    def _extract_scholarship_items(self, payload: Any) -> list[dict[str, Any]]:
        data = self._extract_data(payload)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            if isinstance(data.get("items"), list):
                return [item for item in data.get("items", []) if isinstance(item, dict)]
            if isinstance(data.get("scholarships"), list):
                return [item for item in data.get("scholarships", []) if isinstance(item, dict)]
        return []

    def _extract_match_results(self, payload: Any) -> list[dict[str, Any]]:
        data = self._extract_data(payload)
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            return [item for item in data.get("results", []) if isinstance(item, dict)]
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return [item for item in data.get("items", []) if isinstance(item, dict)]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_match_entity(match_item: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        direct_entity_type = match_item.get("entity_type")
        direct_entity_id = match_item.get("entity_id")
        if direct_entity_type and direct_entity_id:
            return str(direct_entity_type), str(direct_entity_id)

        nested = match_item.get("match_result")
        if isinstance(nested, dict):
            nested_entity_type = nested.get("entity_type")
            nested_entity_id = nested.get("entity_id")
            if nested_entity_type and nested_entity_id:
                return str(nested_entity_type), str(nested_entity_id)
        return None, None

    def _normalize_match_summary(self, match_item: dict[str, Any]) -> dict[str, Any]:
        target = match_item
        if isinstance(match_item.get("match_result"), dict):
            target = match_item["match_result"]
        return {
            "id": target.get("id"),
            "match_score": self._coerce_float(target.get("match_score")),
            "confidence_level": target.get("confidence_level"),
            "created_at": target.get("created_at"),
        }

    @staticmethod
    def _to_error(service: str, message: str) -> dict[str, Any]:
        return {"service": service, "message": message}

    @staticmethod
    def _first_non_empty(*values: Any) -> Optional[str]:
        for value in values:
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    return stripped
        return None

    @staticmethod
    def _normalize_program_degree(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower().replace("_", " ")
        mapping = {
            # Bachelor variations
            "bachelor": "bachelors",
            "bachelors": "bachelors",
            "bachelor degree": "bachelors",
            "bachelors degree": "bachelors",
            "bachelor's": "bachelors",
            "bachelor's degree": "bachelors",
            "undergraduate": "bachelors",
            "undergrad": "bachelors",
            # Master variations
            "master": "masters",
            "masters": "masters",
            "master degree": "masters",
            "masters degree": "masters",
            "master's": "masters",
            "master's degree": "masters",
            "postgraduate": "masters",
            "graduate": "masters",
            # PhD variations
            "phd": "phd",
            "ph.d": "phd",
            "ph.d.": "phd",
            "doctorate": "phd",
            "doctoral": "phd",
            "doctor": "phd",
            # Other
            "diploma": "diploma",
            "certificate": "certificate",
        }
        return mapping.get(normalized, value)

    @staticmethod
    def _normalize_scholarship_degree(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower().replace("_", " ")
        mapping = {
            "bachelor": "bachelor",
            "bachelors": "bachelor",
            "undergraduate": "bachelor",
            "master": "master",
            "masters": "master",
            "phd": "phd",
            "doctorate": "phd",
        }
        return mapping.get(normalized, value)

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((time.perf_counter() - started_at) * 1000))

    @staticmethod
    def _truncate_payload(payload: Any, max_items: int = 20) -> Optional[dict[str, Any]]:
        if not isinstance(payload, dict):
            return None
        truncated: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, str):
                truncated[key] = value[:500]
            elif isinstance(value, list):
                truncated[key] = value[:max_items]
                truncated[f"{key}_count"] = len(value)
            elif isinstance(value, dict):
                truncated[key] = dict(list(value.items())[: max_items // 2])
            else:
                truncated[key] = value
        return truncated

    @classmethod
    def _cache_get(
        cls,
        cache: OrderedDict[str, tuple[float, dict[str, Any]]],
        key: str,
    ) -> Optional[dict[str, Any]]:
        cached = cache.get(key)
        if cached is None:
            return None
        expires_at, payload = cached
        if time.monotonic() >= expires_at:
            cache.pop(key, None)
            return None
        cache.move_to_end(key)
        return dict(payload)

    @classmethod
    def _cache_set(
        cls,
        cache: OrderedDict[str, tuple[float, dict[str, Any]]],
        *,
        key: str,
        payload: dict[str, Any],
        ttl_seconds: int,
    ) -> None:
        cache[key] = (time.monotonic() + ttl_seconds, dict(payload))
        cache.move_to_end(key)
        cls._cache_prune(cache)

    @classmethod
    def _cache_prune(cls, cache: OrderedDict[str, tuple[float, dict[str, Any]]]) -> None:
        now = time.monotonic()
        expired = [k for k, (expires_at, _) in cache.items() if expires_at <= now]
        for key in expired:
            cache.pop(key, None)
        while len(cache) > cls._CACHE_MAX_ENTRIES:
            cache.popitem(last=False)

    @classmethod
    def _dashboard_cache_key(cls, user_id: str) -> str:
        return f"dashboard:{user_id}"

    @classmethod
    def _result_cache_key(cls, user_id: str, workflow_id: str) -> str:
        return f"result:{user_id}:{workflow_id}"

    def _get_dashboard_cache(self, user_id: str) -> Optional[dict[str, Any]]:
        return self._cache_get(self._DASHBOARD_CACHE, self._dashboard_cache_key(user_id))

    def _set_dashboard_cache(self, user_id: str, payload: dict[str, Any]) -> None:
        self._cache_set(
            self._DASHBOARD_CACHE,
            key=self._dashboard_cache_key(user_id),
            payload=payload,
            ttl_seconds=self._DASHBOARD_CACHE_TTL_SECONDS,
        )

    def _invalidate_dashboard_cache(self, user_id: str) -> None:
        self._DASHBOARD_CACHE.pop(self._dashboard_cache_key(user_id), None)

    def _get_result_cache(self, user_id: str, workflow_id: str) -> Optional[dict[str, Any]]:
        return self._cache_get(self._RESULT_CACHE, self._result_cache_key(user_id, workflow_id))

    def _set_result_cache(self, user_id: str, workflow_id: str, payload: dict[str, Any]) -> None:
        self._cache_set(
            self._RESULT_CACHE,
            key=self._result_cache_key(user_id, workflow_id),
            payload=payload,
            ttl_seconds=self._RESULT_CACHE_TTL_SECONDS,
        )

    def _invalidate_result_cache(self, user_id: str, workflow_id: str) -> None:
        self._RESULT_CACHE.pop(self._result_cache_key(user_id, workflow_id), None)
