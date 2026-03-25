"""Health-check endpoints."""

from fastapi import APIRouter

from app.config import APP_VERSION

router = APIRouter(tags=["Health"])


@router.get("/")
async def root():
    return {
        "message": "Ouroboros Orchestrator Service",
        "version": APP_VERSION,
        "status": "healthy",
    }


@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": APP_VERSION,
        "database": "not_connected",
    }
