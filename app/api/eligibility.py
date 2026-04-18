"""Eligibility orchestration endpoints."""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, Path, Query

from app.middleware.auth_middleware import get_current_user_id
from app.models.common import StandardResponse
from app.models.eligibility import EligibilityEvaluateRequest
from app.services.eligibility_service import (
    EligibilityEvaluationInput,
    EligibilityResultsQuery,
    EligibilityService,
)

router = APIRouter(prefix="/api/v1/eligibility", tags=["Eligibility"])
eligibility_service = EligibilityService()


@router.post(
    "/evaluate",
    response_model=StandardResponse[dict],
    summary="Evaluate eligibility for a program or scholarship",
)
async def evaluate_eligibility(
    body: EligibilityEvaluateRequest,
    user_id: str = Depends(get_current_user_id),
    trace_id: Optional[str] = Header(default=None, alias="X-Trace-ID"),
):
    """Proxy an evaluation request to the eligibility engine using the authenticated user ID."""
    return await eligibility_service.evaluate(
        EligibilityEvaluationInput(
            user_id=user_id,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            user_profile=body.user_profile,
            entity_data=body.entity_data,
            include_attribution=body.include_attribution,
        ),
        trace_id=trace_id,
    )


@router.get(
    "/results",
    response_model=StandardResponse[dict],
    summary="List eligibility results for the authenticated user",
)
async def get_results(
    entity_type: Optional[Literal["program", "scholarship"]] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
    trace_id: Optional[str] = Header(default=None, alias="X-Trace-ID"),
):
    """Return paginated eligibility results for the current authenticated user."""
    return await eligibility_service.get_results(
        EligibilityResultsQuery(
            user_id=user_id,
            entity_type=entity_type,
            page=page,
            page_size=page_size,
        ),
        trace_id=trace_id,
    )


@router.get(
    "/results/{match_id}",
    response_model=StandardResponse[dict],
    summary="Get a single eligibility result",
)
async def get_result_detail(
    match_id: str = Path(..., description="Match result ID from the eligibility engine"),
    _user_id: str = Depends(get_current_user_id),
    trace_id: Optional[str] = Header(default=None, alias="X-Trace-ID"),
):
    """Return a single match result by ID."""
    return await eligibility_service.get_result_detail(match_id=match_id, trace_id=trace_id)


@router.get(
    "/attribution/{match_id}",
    response_model=StandardResponse[dict],
    summary="Get attribution details for a match result",
)
async def get_attribution_report(
    match_id: str = Path(..., description="Match result ID from the eligibility engine"),
    _user_id: str = Depends(get_current_user_id),
    trace_id: Optional[str] = Header(default=None, alias="X-Trace-ID"),
):
    """Return attribution/explainability details for a match result."""
    return await eligibility_service.get_attribution_report(match_id=match_id, trace_id=trace_id)
