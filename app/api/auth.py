"""Authentication API endpoints (phone-based JWT with Twilio OTP)."""

from fastapi import APIRouter, Body, Depends, Query
from fastapi.openapi.models import Example
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.middleware.auth_middleware import get_client_info, get_current_user, get_current_user_id
from app.models.auth import (
    LoginRequest,
    LogoutResponse,
    ProfileStatusResponse,
    ProfileUpdateRequest,
    RefreshRequest,
    ResendOTPRequest,
    ResendOTPResponse,
    SessionResponse,
    SignupRequest,
    SignupResponse,
    TokenResponse,
    UserResponse,
    VerifyOTPRequest,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer(scheme_name="HTTPBearer")

# Swagger merges per-field examples into one JSON blob; use explicit body examples for XOR login.
_EXAMPLE_LOGIN_PASSWORD = "MyP@ssw0rd"  # nosec B105

_LOGIN_OPENAPI_EXAMPLES: dict[str, Example] = {
    "phone_number": Example(
        summary="Login with phone",
        description="Send **phone_number** + **password** only (omit username).",
        value={"phone_number": "+6591234567", "password": _EXAMPLE_LOGIN_PASSWORD},
    ),
    "username": Example(
        summary="Login with username",
        description="Send **username** + **password** only (omit phone_number).",
        value={"username": "alice_wonder", "password": _EXAMPLE_LOGIN_PASSWORD},
    ),
}

auth_service = AuthService()


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=201,
    summary="Register a new user",
    responses={
        201: {"description": "User created, OTP sent for phone verification"},
        409: {"description": "Phone number or username already registered"},
        429: {"description": "OTP rate limit exceeded"},
    },
)
async def signup(body: SignupRequest, client: dict = Depends(get_client_info)):
    """
    Register with **phone number**, **username**, **first/last name**, and **password**.

    An OTP is sent via SMS to verify the phone number.
    After signup, call `POST /auth/verify-otp` with the code received.
    """
    return await auth_service.signup(
        username=body.username,
        phone_number=body.phone_number,
        password=body.password,
        first_name=body.first_name,
        last_name=body.last_name,
        ip_address=client["ip_address"],
        user_agent=client["user_agent"],
    )


@router.post(
    "/verify-otp",
    response_model=TokenResponse,
    summary="Verify phone OTP",
    responses={
        200: {"description": "Phone verified, JWT tokens returned"},
        400: {"description": "Invalid or expired OTP"},
        429: {"description": "Too many failed attempts"},
    },
)
async def verify_otp(body: VerifyOTPRequest, client: dict = Depends(get_client_info)):
    """
    Verify the 6-digit OTP sent to the phone number during signup.

    On success, returns **access_token** and **refresh_token**.
    The user's phone is marked as verified.
    """
    return await auth_service.verify_otp(
        phone_number=body.phone_number,
        otp_code=body.otp_code,
        ip_address=client["ip_address"],
        user_agent=client["user_agent"],
    )


@router.post(
    "/resend-otp",
    response_model=ResendOTPResponse,
    summary="Resend OTP",
    responses={
        200: {"description": "New OTP sent"},
        429: {"description": "Cooldown or rate limit active"},
    },
)
async def resend_otp(body: ResendOTPRequest, client: dict = Depends(get_client_info)):
    """
    Resend OTP to an unverified phone number.

    Rate-limited: **max 3 per 15 min**, **30 s cooldown** between sends.
    """
    return await auth_service.resend_otp(
        phone_number=body.phone_number,
        ip_address=client["ip_address"],
        user_agent=client["user_agent"],
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login",
    responses={
        200: {"description": "JWT tokens returned with user profile"},
        401: {"description": "Invalid credentials"},
        403: {"description": "Account disabled or phone not verified"},
    },
)
async def login(
    body: LoginRequest = Body(..., openapi_examples=_LOGIN_OPENAPI_EXAMPLES),
    client: dict = Depends(get_client_info),
):
    """
    Login with **phone number** or **username** + **password**.

    Requires the phone to be verified via OTP first.
    The response includes a `profile_completed` flag — if `false`,
    the client should prompt the user to complete their profile via `PATCH /auth/profile`.
    """
    return await auth_service.login(
        phone_number=body.phone_number,
        username=body.username,
        password=body.password,
        ip_address=client["ip_address"],
        user_agent=client["user_agent"],
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh token pair",
    responses={
        200: {"description": "New token pair issued"},
        401: {"description": "Invalid, expired, or revoked refresh token"},
    },
)
async def refresh_tokens(body: RefreshRequest, client: dict = Depends(get_client_info)):
    """
    Exchange a **refresh token** for a new access + refresh token pair.

    The old refresh token is rotated (invalidated). Each refresh token can only be used once.
    """
    result = await auth_service.refresh_tokens(
        refresh_token=body.refresh_token,
        ip_address=client["ip_address"],
        user_agent=client["user_agent"],
    )
    return {
        "access_token": result["access_token"],
        "refresh_token": result["refresh_token"],
        "token_type": result["token_type"],
        "expires_in": result["expires_in"],
    }


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Logout (revoke session)",
    responses={200: {"description": "Session revoked"}},
)
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    _user: dict = Depends(get_current_user),
):
    """Revoke the session tied to the current access token."""
    return await auth_service.logout(credentials.credentials)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
async def get_me(user_id: str = Depends(get_current_user_id)):
    """Return the authenticated user's full profile. Updates `last_active`."""
    return await auth_service.get_profile(user_id)


@router.patch(
    "/profile",
    response_model=UserResponse,
    summary="Update profile",
    responses={
        200: {"description": "Profile updated; profile_completed true when all completion fields are set"},
        404: {"description": "User not found"},
    },
)
async def update_profile(body: ProfileUpdateRequest, user_id: str = Depends(get_current_user_id)):
    """
    Complete or update user profile.

    After first login, the client should call this to set **email**,
    **about_me**, **profession**, and **interest** (jobs, startups, research, or degree).
    Any non-null field is updated; null fields are left unchanged.

    ``profile_completed`` becomes **true** only when **all four** are present
    (non-empty email, about_me, profession, and a valid interest). If the user
    later clears required data, it becomes **false** again.
    """
    return await auth_service.update_profile(
        user_id=user_id,
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        about_me=body.about_me,
        profession=body.profession,
        interest=body.interest,
    )


@router.get(
    "/profile-status",
    response_model=ProfileStatusResponse,
    summary="Check profile completion status",
)
async def profile_status(user_id: str = Depends(get_current_user_id)):
    """Check whether the user's phone is verified and profile is completed."""
    return await auth_service.get_profile_status(user_id)


@router.get(
    "/sessions",
    response_model=list[SessionResponse],
    summary="List user sessions",
    responses={200: {"description": "List of active (or all) sessions for the current user"}},
)
async def list_sessions(
    active_only: bool = Query(True, description="If true, only return active (non-revoked, non-expired) sessions"),
    user_id: str = Depends(get_current_user_id),
):
    """
    List the authenticated user's sessions.

    Useful for "active devices" UI or auditing login history.
    Each session includes **created_at**, **last_active_at**, **user_agent**,
    and **ip_address** so users can see when and where they logged in.
    """
    return await auth_service.get_sessions(user_id, active_only=active_only)
