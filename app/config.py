"""Application configuration loaded from environment variables."""

import json
import os
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.2.0"


class Settings(BaseSettings):
    """All application settings. Loaded from .env file."""

    # ---------- Database ----------
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_NAME: str = "ouroboros_orchestrator_db"
    DB_USERNAME: str = "root"
    DB_PASSWORD: str = ""

    DB_POOL_SIZE: int = 10
    DB_POOL_NAME: str = "orchestrator_pool"
    DB_CONNECTION_TIMEOUT: int = 20
    DB_POOL_LOG_CONNECTIONS: bool = False

    # ---------- JWT (RS256 — self-rolled) ----------
    JWT_PRIVATE_KEY: str = ""
    JWT_PUBLIC_KEY: str = ""
    JWT_ACCESS_TOKEN_EXP_SECONDS: int = 900
    JWT_REFRESH_TOKEN_EXP_SECONDS: int = 604800
    JWT_ISSUER: str = "ouroboros.ai/auth"
    JWT_AUDIENCE: str = "ouroboros-api"

    # ---------- Twilio (OTP delivery) ----------
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    TWILIO_VERIFY_SERVICE_SID: str = ""

    # ---------- OTP ----------
    OTP_LENGTH: int = 6
    OTP_EXPIRY_SECONDS: int = 300
    OTP_MAX_ATTEMPTS: int = 3
    OTP_COOLDOWN_SECONDS: int = 30
    OTP_RATE_LIMIT_WINDOW_SECONDS: int = 900
    OTP_RATE_LIMIT_MAX_REQUESTS: int = 3

    # ---------- Allowed Phone Countries (ISO 3166-1 alpha-2) ----------
    ALLOWED_COUNTRY_CODES: str = '["SG","IN","VN","ID","MY","US","CA","AU"]'

    # ---------- Agent Services ----------
    STUDENT_PROFILE_SERVICE_URL: str = "http://localhost:8001"
    PROGRAM_DISCOVERY_SERVICE_URL: str = "http://localhost:8002"
    SCHOLARSHIP_DISCOVERY_SERVICE_URL: str = "http://localhost:8003"
    ELIGIBILITY_SERVICE_URL: str = "http://localhost:8004"
    APPLICATION_SUPPORT_SERVICE_URL: str = "http://localhost:8005"

    # ---------- Inter-Service Auth ----------
    X_SERVICE_TOKEN: str = ""

    # ---------- HTTP Client ----------
    AGENT_CALL_TIMEOUT: int = 30
    AGENT_CALL_RETRIES: int = 2
    AGENT_CALL_BACKOFF_FACTOR: float = 1.0

    # ---------- Application ----------
    LOG_LEVEL: str = "INFO"
    USE_MOCK_DATA: bool = True
    ALLOW_DB_FAILURE: bool = False
    CORS_ORIGINS: str = "http://localhost:8080,http://localhost:3000,http://localhost:5173"

    # ---------- Docker ----------
    RUN_STARTUP_SCRIPTS: bool = True
    SEED_DATABASE: bool = True
    DOCKER_MYSQL_PORT: int = 3307

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    # ── helpers ──────────────────────────────────────────────────

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

    def get_allowed_country_codes(self) -> List[str]:
        """Parse ALLOWED_COUNTRY_CODES JSON string into a list."""
        try:
            return json.loads(self.ALLOWED_COUNTRY_CODES)
        except (json.JSONDecodeError, TypeError):
            return ["SG", "IN", "VN", "ID", "MY", "US", "CA", "AU"]


settings = Settings()
