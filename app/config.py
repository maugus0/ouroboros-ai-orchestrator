"""Application configuration loaded from environment variables."""

import os

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.1.0"


class Settings(BaseSettings):
    """All application settings. Loaded from .env file."""

    # ========== Database ==========
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_NAME: str = "ouroboros_orchestrator_db"
    DB_USERNAME: str = "root"
    DB_PASSWORD: str = ""

    # Database pool
    DB_POOL_SIZE: int = 10
    DB_POOL_NAME: str = "orchestrator_pool"
    DB_CONNECTION_TIMEOUT: int = 20
    DB_POOL_LOG_CONNECTIONS: bool = False

    # ========== Auth0 Configuration ==========
    AUTH0_DOMAIN: str = ""  # e.g., "ouroboros-dev.us.auth0.com"
    AUTH0_API_AUDIENCE: str = ""  # e.g., "https://api.ouroboros.ai"
    AUTH0_ALGORITHMS: str = "RS256"  # Comma-separated if multiple

    # ========== JWT (RS256 - Legacy, kept for backward compatibility) ==========
    JWT_PRIVATE_KEY: str = ""
    JWT_PUBLIC_KEY: str = ""
    JWT_ACCESS_TOKEN_EXP_SECONDS: int = 3600
    JWT_REFRESH_TOKEN_EXP_SECONDS: int = 2592000
    JWT_ISSUER: str = "ouroboros.ai/auth"
    JWT_AUDIENCE: str = "ouroboros-api"

    # ========== Agent Services ==========
    STUDENT_PROFILE_SERVICE_URL: str = "http://localhost:8001"
    PROGRAM_DISCOVERY_SERVICE_URL: str = "http://localhost:8002"
    SCHOLARSHIP_DISCOVERY_SERVICE_URL: str = "http://localhost:8003"
    ELIGIBILITY_SERVICE_URL: str = "http://localhost:8004"
    APPLICATION_SUPPORT_SERVICE_URL: str = "http://localhost:8005"

    # ========== Inter-Service Auth ==========
    X_SERVICE_TOKEN: str = ""

    # ========== HTTP Client ==========
    AGENT_CALL_TIMEOUT: int = 30
    AGENT_CALL_RETRIES: int = 2
    AGENT_CALL_BACKOFF_FACTOR: float = 1.0

    # ========== Application ==========
    LOG_LEVEL: str = "INFO"
    USE_MOCK_DATA: bool = True
    ALLOW_DB_FAILURE: bool = False
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # ========== Docker ==========
    RUN_STARTUP_SCRIPTS: bool = True
    SEED_DATABASE: bool = True
    DOCKER_MYSQL_PORT: int = 3307

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    def get_db_host(self) -> str:
        return os.getenv("MYSQL_HOST", self.DB_HOST)

    def get_db_name(self) -> str:
        return os.getenv("MYSQL_DATABASE", self.DB_NAME)

    def get_db_user(self) -> str:
        return os.getenv("MYSQL_USER", self.DB_USERNAME)

    def get_db_password(self) -> str:
        return os.getenv("MYSQL_PASSWORD", self.DB_PASSWORD)

    def get_db_port(self) -> int:
        val = os.getenv("MYSQL_PORT")
        return int(val) if val is not None else self.DB_PORT

    def get_cors_origins_list(self) -> list:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    @property
    def auth0_issuer(self) -> str:
        """Auth0 issuer URL (derived from domain)."""
        return f"https://{self.AUTH0_DOMAIN}/"

    @property
    def auth0_jwks_uri(self) -> str:
        """Auth0 JWKS endpoint for public key retrieval."""
        return f"https://{self.AUTH0_DOMAIN}/.well-known/jwks.json"

    def get_auth0_algorithms(self) -> list[str]:
        """Parse AUTH0_ALGORITHMS as a list."""
        return [alg.strip() for alg in self.AUTH0_ALGORITHMS.split(",")]


settings = Settings()
