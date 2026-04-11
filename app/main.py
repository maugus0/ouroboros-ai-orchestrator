"""FastAPI application entry point for the Ouroboros Orchestrator Service."""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.api import auth, chats, health, projects
from app.config import APP_VERSION, settings
from app.core.database import PoolConfig, close_pool, create_pool
from app.core.logging import get_logger, setup_logging
from app.middleware.logging_middleware import LoggingMiddleware
from app.utils.utc_json_response import UTCJSONResponse

load_dotenv()
setup_logging(log_level=settings.LOG_LEVEL)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_application: FastAPI):
    """Startup: create DB pool. Shutdown: close pool."""
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
    description=(
        "Central coordination service for the Ouroboros AI scholarship discovery platform. "
        "Handles phone-based JWT authentication (RS256), Twilio OTP verification, "
        "user profile management, and health monitoring."
    ),
    lifespan=lifespan,
    default_response_class=UTCJSONResponse,
    swagger_ui_parameters={
        "persistAuthorization": True,
        "displayRequestDuration": True,
        "filter": True,
        "docExpansion": "none",
    },
    openapi_tags=[
        {
            "name": "Authentication",
            "description": (
                "Phone-based JWT authentication with Twilio OTP verification. "
                "Handles signup, OTP verify, login, token refresh, logout, and profile management."
            ),
        },
        {
            "name": "Chats",
            "description": (
                "Chat session management. Create conversations, send messages, "
                "view history, star chats, and organize into projects."
            ),
        },
        {
            "name": "Projects",
            "description": (
                "Project management. Create folders to organize chats into groups "
                "with custom names, colors, and icons."
            ),
        },
        {"name": "Health", "description": "System health and readiness checks."},
    ],
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

# ── Routers ──────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(chats.router)
app.include_router(projects.router)
app.include_router(health.router)


# ── Custom OpenAPI (adds JWT Bearer auth to Swagger) ─────────────


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )
    schema.setdefault("components", {})
    schema["components"]["securitySchemes"] = {
        "HTTPBearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Paste your JWT access token (without 'Bearer ' prefix).",
        }
    }
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi  # type: ignore[assignment]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)  # nosec B104
