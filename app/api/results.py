"""Aggregated discovery result endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.middleware.auth_middleware import get_current_user_id
from app.models.results import AggregatedResultResponse, DashboardResponse, DiscoverRequest, DiscoverResponse
from app.services.result_aggregation_service import ResultAggregationService

router = APIRouter(prefix="/api/v1", tags=["Results"])


def _get_result_aggregation_service() -> ResultAggregationService:
    return ResultAggregationService()


@router.post("/discover", response_model=DiscoverResponse, summary="Trigger full discovery aggregation pipeline")
async def discover(
    body: DiscoverRequest,
    user_id: str = Depends(get_current_user_id),
    service: ResultAggregationService = Depends(_get_result_aggregation_service),
):
    return await service.discover(user_id=user_id, request=body)


@router.get(
    "/results/{workflow_id}",
    response_model=AggregatedResultResponse,
    summary="Fetch aggregated result by workflow ID",
)
async def get_result_by_workflow(
    workflow_id: str,
    include_versions: bool = Query(default=False),
    user_id: str = Depends(get_current_user_id),
    service: ResultAggregationService = Depends(_get_result_aggregation_service),
):
    result = await service.get_workflow_result(
        user_id=user_id,
        workflow_id=workflow_id,
        include_versions=include_versions,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Workflow result not found")
    return result


@router.get("/dashboard", response_model=DashboardResponse, summary="Fetch latest aggregated dashboard view")
async def get_dashboard(
    include_history: bool = Query(default=True),
    history_limit: int = Query(default=10, ge=1, le=50),
    user_id: str = Depends(get_current_user_id),
    service: ResultAggregationService = Depends(_get_result_aggregation_service),
):
    return await service.get_dashboard(
        user_id=user_id,
        include_history=include_history,
        history_limit=history_limit,
    )
