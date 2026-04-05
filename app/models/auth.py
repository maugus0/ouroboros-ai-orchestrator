"""Pydantic models for authentication endpoints."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserResponse(BaseModel):
    """Response model for user profile data."""

    id: str
    name: str
    email: str
    auth0_sub: Optional[str] = None
    auth_provider: Optional[str] = None
    is_active: bool
    last_login: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserUpdateRequest(BaseModel):
    """Request model for updating user profile."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None


class LogoutResponse(BaseModel):
    """Response model for logout endpoint."""

    message: str = "Logged out successfully"
    detail: str = "Clear tokens on client side to complete logout"


# ============================================
# Legacy models (deprecated - kept for reference)
# ============================================
# Auth0 handles signup/login/refresh directly.
# These are kept for backward compatibility if needed.


class SignupRequest(BaseModel):
    """DEPRECATED: Auth0 handles user registration."""

    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    """DEPRECATED: Auth0 handles authentication."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """DEPRECATED: Auth0 issues tokens directly."""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    """DEPRECATED: Auth0 handles token refresh."""

    refresh_token: str
