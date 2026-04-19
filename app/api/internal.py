"""Internal platform endpoints for service-to-service infrastructure."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.config import settings
from app.security.internal_token_jwks import build_internal_token_jwks

router = APIRouter(prefix="/internal", tags=["Internal"])


@router.get("/.well-known/jwks.json")
async def get_internal_jwks() -> JSONResponse:
    """Expose internal token verification keys for downstream services."""
    try:
        jwks = build_internal_token_jwks()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not jwks["keys"]:
        raise HTTPException(status_code=503, detail="Internal JWKS is not configured")

    return JSONResponse(
        content=jwks,
        headers={"Cache-Control": f"public, max-age={settings.INTERNAL_TOKEN_JWKS_CACHE_MAX_AGE_SECONDS}"},
    )
