"""Health-check endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import APP_VERSION
from app.core.database import get_pool


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str = Field(..., examples=["healthy"], description="Overall service status when DB is up")
    version: str = Field(..., examples=[APP_VERSION], description="Application version from config")
    database: str = Field(
        ...,
        examples=["connected"],
        description="`connected` | `not_connected` (no pool) | `error` (probe failed)",
    )


class RootResponse(BaseModel):
    """Root endpoint response model."""

    message: str = Field(..., examples=["Ouroboros Orchestrator Service"])
    version: str = Field(..., examples=[APP_VERSION])
    status: str = Field(..., examples=["healthy"])


router = APIRouter(tags=["Health"])


@router.get("/", response_model=RootResponse)
async def root():
    """
    Root endpoint - basic service info.

    Returns service name, version, and status.
    """
    return RootResponse(
        message="Ouroboros Orchestrator Service",
        version=APP_VERSION,
        status="healthy",
    )


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Detailed health check endpoint.

    Checks database connectivity and returns overall service health.
    Use this endpoint for readiness probes in Kubernetes/Docker.
    """
    db_status = "not_connected"

    try:
        pool = get_pool()
        if pool:
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT 1")
                    await cursor.fetchone()
                    db_status = "connected"
    except Exception:  # pylint: disable=broad-exception-caught  # noqa: BLE001
        db_status = "error"

    return HealthResponse(
        status="healthy" if db_status == "connected" else "degraded",
        version=APP_VERSION,
        database=db_status,
    )
