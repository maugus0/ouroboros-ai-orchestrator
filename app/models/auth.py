"""Pydantic request/response models for phone-based authentication."""

import re
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

PASSWORD_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&#])[A-Za-z\d@$!%*?&#]{8,}$")
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,20}$")


# ── Requests ─────────────────────────────────────────────────────


class SignupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=20, examples=["alice_wonder"])
    phone_number: str = Field(..., examples=["+6591234567"])
    password: str = Field(..., min_length=8, examples=["MyP@ssw0rd"])
    first_name: str = Field(..., min_length=1, max_length=50, examples=["Alice"])
    last_name: str = Field(..., min_length=1, max_length=50, examples=["Smith"])

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        if not USERNAME_RE.match(v):
            raise ValueError("Username must be 3-20 characters: letters, digits, underscore only")
        return v.lower()

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if not PASSWORD_RE.match(v):
            raise ValueError(
                "Password must be >=8 chars with uppercase, lowercase, digit, and special character (@$!%*?&#)"
            )
        return v


class VerifyOTPRequest(BaseModel):
    phone_number: str = Field(..., examples=["+6591234567"])
    otp_code: str = Field(..., min_length=6, max_length=6, examples=["123456"])

    @field_validator("otp_code")
    @classmethod
    def _otp_digits(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("OTP must be 6 digits")
        return v


class ResendOTPRequest(BaseModel):
    phone_number: str = Field(..., examples=["+6591234567"])


class LoginRequest(BaseModel):
    phone_number: Optional[str] = Field(None, examples=["+6591234567"])
    username: Optional[str] = Field(None, examples=["alice_wonder"])
    password: str = Field(..., examples=["MyP@ssw0rd"])

    def model_post_init(self, __context: Any) -> None:  # pylint: disable=arguments-differ
        if not self.phone_number and not self.username:
            raise ValueError("Either phone_number or username must be provided")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., examples=["eyJhbGciOiJSUzI1NiIs..."])


class ProfileUpdateRequest(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=50, examples=["Alice"])
    last_name: Optional[str] = Field(None, min_length=1, max_length=50, examples=["Smith"])
    email: Optional[EmailStr] = Field(None, examples=["alice@example.com"])
    about_me: Optional[str] = Field(None, max_length=500, examples=["Full-stack dev passionate about AI"])
    profession: Optional[str] = Field(None, max_length=100, examples=["Software Engineer"])
    interest: Optional[str] = Field(None, pattern=r"^(jobs|startups|research)$", examples=["startups"])


# ── Responses ────────────────────────────────────────────────────


class SignupResponse(BaseModel):
    user_id: str = Field(..., examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"])
    username: str = Field(..., examples=["alice_wonder"])
    phone_number: str = Field(..., description="Masked phone number", examples=["+65****4567"])
    message: str = Field(..., examples=["OTP sent to your phone. Please verify to complete registration."])


class ResendOTPResponse(BaseModel):
    message: str = Field(..., examples=["OTP sent to your phone"])
    phone_number: str = Field(..., description="Masked phone number", examples=["+65****4567"])


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"  # nosec B105
    expires_in: int = Field(..., examples=[900])
    user: Optional[dict[str, Any]] = None
    profile_completed: Optional[bool] = Field(None, examples=[False])


class LogoutResponse(BaseModel):
    message: str = Field(..., examples=["Logged out successfully"])


class UserResponse(BaseModel):
    id: str
    username: Optional[str] = None
    phone_number: Optional[str] = None
    phone_country_code: Optional[str] = None
    phone_verified: Optional[bool] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    about_me: Optional[str] = None
    profession: Optional[str] = None
    interest: Optional[str] = None
    profile_completed: Optional[bool] = None
    is_active: Optional[bool] = None
    last_login: Optional[datetime] = None
    last_active: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SessionResponse(BaseModel):
    id: str
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    is_revoked: Optional[bool] = None
    revoked_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class ProfileStatusResponse(BaseModel):
    profile_completed: bool
    phone_verified: bool
