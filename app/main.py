"""FastAPI application entry point for the Ouroboros Orchestrator Service."""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, health
from app.config import APP_VERSION, settings
from app.core.database import PoolConfig, close_pool, create_pool
from app.core.logging import get_logger, setup_logging
from app.middleware.logging_middleware import LoggingMiddleware

load_dotenv()


@asynccontextmanager
async def lifespan(_application: FastAPI):
    """Application startup and shutdown lifecycle."""
    setup_logging(log_level=settings.LOG_LEVEL)
    logger = get_logger("startup")

    logger.info("orchestrator_starting", version=APP_VERSION)

    if not settings.ALLOW_DB_FAILURE:
        try:
            await create_pool(
                PoolConfig(
                    host=settings.get_db_host(),
                    port=settings.get_db_port(),
                    db=settings.get_db_name(),
                    user=settings.get_db_user(),
                    password=settings.get_db_password(),
                    pool_size=settings.DB_POOL_SIZE,
                )
            )
        except Exception as exc:
            logger.error("database_connection_failed", error=str(exc))
            raise
    else:
        logger.warning("database_skipped", reason="ALLOW_DB_FAILURE is True")

    yield

    await close_pool()
    logger.info("orchestrator_stopped")


app = FastAPI(
    title="Ouroboros Orchestrator",
    version=APP_VERSION,
    description="Central coordination service for the Ouroboros AI scholarship discovery platform",
    lifespan=lifespan,
    swagger_ui_parameters={
        "persistAuthorization": True,
        "displayRequestDuration": True,
        "filter": True,
        "docExpansion": "none",
    },
    swagger_ui_init_oauth={
        "clientId": settings.AUTH0_CLIENT_ID,
        "usePkceWithAuthorizationCodeGrant": True,
        "additionalQueryStringParams": {"audience": settings.AUTH0_API_AUDIENCE},
    },
)

# ── Middleware ────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LoggingMiddleware)

# ── Routers (Authentication first, then Health) ──────────────────

app.include_router(auth.router)
app.include_router(health.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)
