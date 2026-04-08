"""Tests for the AuthService (mocked repos + Twilio)."""

# Pytest injects fixtures by parameter name; names match fixture definitions.
# pylint: disable=redefined-outer-name

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.services.auth_service import AuthService
from app.utils.jwt_util import JWTUtil
from app.utils.password_util import hash_password


@pytest.fixture
def repos():
    return AsyncMock(), AsyncMock()


@pytest.fixture
def twilio_mock():
    svc = AsyncMock()
    svc.send_otp.return_value = MagicMock(success=True, message_sid="SM123", error_message=None)
    return svc


@pytest.fixture
def service(repos, twilio_mock):
    user_repo, auth_repo = repos
    return AuthService(user_repo=user_repo, auth_repo=auth_repo, jwt_util=JWTUtil(), twilio_service=twilio_mock)


class TestSignup:
    @pytest.mark.asyncio
    async def test_success(self, service, repos, twilio_mock):
        user_repo, auth_repo = repos
        user_repo.phone_exists.return_value = False
        user_repo.username_exists.return_value = False
        user_repo.get_otp_send_count.return_value = 0
        user_repo.create.return_value = {
            "id": "uid-1",
            "username": "alice",
            "phone_number": "+6591234567",
            "first_name": "Alice",
            "last_name": "Smith",
        }

        result = await service.signup(
            username="alice",
            phone_number="+6591234567",
            password="StrongP@ss1",
            first_name="Alice",
            last_name="Smith",
        )

        assert result["user_id"] == "uid-1"
        assert "****" in result["phone_number"]
        user_repo.create.assert_called_once()
        twilio_mock.send_otp.assert_called_once()
        auth_repo.log_otp_action.assert_called_once()

    @pytest.mark.asyncio
    async def test_duplicate_phone_409(self, service, repos):
        user_repo, _ = repos
        user_repo.phone_exists.return_value = True

        with pytest.raises(HTTPException) as exc:
            await service.signup(
                username="bob",
                phone_number="+6591234567",
                password="StrongP@ss1",
                first_name="Bob",
                last_name="Jones",
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_duplicate_username_409(self, service, repos):
        user_repo, _ = repos
        user_repo.phone_exists.return_value = False
        user_repo.username_exists.return_value = True

        with pytest.raises(HTTPException) as exc:
            await service.signup(
                username="alice",
                phone_number="+6591234567",
                password="StrongP@ss1",
                first_name="Alice",
                last_name="Smith",
            )
        assert exc.value.status_code == 409


class TestVerifyOTP:
    @pytest.mark.asyncio
    async def test_success(self, service, repos):
        user_repo, auth_repo = repos
        user_repo.get_by_phone.return_value = {
            "id": "uid-1",
            "username": "alice",
            "phone_number": "+6591234567",
            "phone_verified": False,
            "otp_code": "123456",
            "otp_expires_at": datetime.now(timezone.utc) + timedelta(minutes=3),
            "otp_attempts": 0,
        }
        user_repo.get_by_id.return_value = {
            "id": "uid-1",
            "username": "alice",
            "phone_number": "+6591234567",
            "first_name": "Alice",
            "last_name": "Smith",
            "profile_completed": False,
        }
        auth_repo.create_session.return_value = {"session_id": "sid-1", "expires_at": datetime.now(timezone.utc)}

        result = await service.verify_otp(phone_number="+6591234567", otp_code="123456")

        assert "access_token" in result
        assert "refresh_token" in result
        user_repo.verify_phone.assert_called_once_with("uid-1")

    @pytest.mark.asyncio
    async def test_wrong_otp_400(self, service, repos):
        user_repo, _ = repos
        user_repo.get_by_phone.return_value = {
            "id": "uid-1",
            "phone_verified": False,
            "otp_code": "123456",
            "otp_expires_at": datetime.now(timezone.utc) + timedelta(minutes=3),
            "otp_attempts": 0,
        }

        with pytest.raises(HTTPException) as exc:
            await service.verify_otp(phone_number="+6591234567", otp_code="000000")
        assert exc.value.status_code == 400


class TestLogin:
    @pytest.mark.asyncio
    async def test_success_with_phone(self, service, repos):
        user_repo, auth_repo = repos
        user_repo.get_by_phone.return_value = {
            "id": "uid-1",
            "username": "alice",
            "phone_number": "+6591234567",
            "phone_verified": True,
            "password_hash": hash_password("StrongP@ss1"),
            "is_active": True,
        }
        user_repo.get_by_id.return_value = {
            "id": "uid-1",
            "username": "alice",
            "first_name": "Alice",
            "last_name": "Smith",
            "profile_completed": False,
        }
        auth_repo.create_session.return_value = {"session_id": "sid-1", "expires_at": datetime.now(timezone.utc)}

        result = await service.login(phone_number="+6591234567", password="StrongP@ss1")

        assert "access_token" in result
        assert result["user"]["profile_completed"] is False

    @pytest.mark.asyncio
    async def test_success_with_username(self, service, repos):
        user_repo, auth_repo = repos
        user_repo.get_by_username.return_value = {
            "id": "uid-1",
            "username": "alice",
            "phone_number": "+6591234567",
            "phone_verified": True,
            "password_hash": hash_password("StrongP@ss1"),
            "is_active": True,
        }
        user_repo.get_by_id.return_value = {
            "id": "uid-1",
            "username": "alice",
            "first_name": "Alice",
            "last_name": "Smith",
            "profile_completed": False,
        }
        auth_repo.create_session.return_value = {"session_id": "sid-1", "expires_at": datetime.now(timezone.utc)}

        result = await service.login(username="alice", password="StrongP@ss1")

        assert "access_token" in result
        assert result["user"]["profile_completed"] is False
        user_repo.get_by_username.assert_called_once_with("alice")

    @pytest.mark.asyncio
    async def test_wrong_password_401(self, service, repos):
        user_repo, _ = repos
        user_repo.get_by_phone.return_value = {
            "id": "uid-1",
            "phone_verified": True,
            "password_hash": hash_password("StrongP@ss1"),
            "is_active": True,
        }

        with pytest.raises(HTTPException) as exc:
            await service.login(phone_number="+6591234567", password="WrongP@ss1")
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_unverified_phone_403(self, service, repos):
        user_repo, _ = repos
        user_repo.get_by_phone.return_value = {
            "id": "uid-1",
            "phone_verified": False,
            "password_hash": hash_password("StrongP@ss1"),
            "is_active": True,
        }

        with pytest.raises(HTTPException) as exc:
            await service.login(phone_number="+6591234567", password="StrongP@ss1")
        assert exc.value.status_code == 403


class TestMFALogin:
    @pytest.mark.asyncio
    async def test_mfa_enabled_returns_challenge(self, service, repos, twilio_mock):
        user_repo, _auth_repo = repos
        user_repo.get_by_phone.return_value = {
            "id": "uid-1",
            "username": "alice",
            "phone_number": "+6591234567",
            "phone_verified": True,
            "password_hash": hash_password("StrongP@ss1"),
            "is_active": True,
            "mfa_enabled": True,
        }
        user_repo.get_otp_send_count.return_value = 0

        result = await service.login(phone_number="+6591234567", password="StrongP@ss1")

        assert result["mfa_required"] is True
        assert result["user_id"] == "uid-1"
        assert "****" in result["phone_number"]
        twilio_mock.send_otp.assert_called_once()
        user_repo.set_otp.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_mfa_success(self, service, repos):
        user_repo, auth_repo = repos
        user_repo.get_by_id_with_otp.return_value = {
            "id": "uid-1",
            "username": "alice",
            "phone_number": "+6591234567",
            "phone_verified": True,
            "mfa_enabled": True,
            "otp_code": "654321",
            "otp_expires_at": datetime.now(timezone.utc) + timedelta(minutes=3),
            "otp_attempts": 0,
        }
        user_repo.get_by_id.return_value = {
            "id": "uid-1",
            "username": "alice",
            "first_name": "Alice",
            "last_name": "Smith",
            "profile_completed": False,
        }
        auth_repo.create_session.return_value = {"session_id": "sid-1", "expires_at": datetime.now(timezone.utc)}

        result = await service.verify_mfa(user_id="uid-1", otp_code="654321")

        assert "access_token" in result
        assert "refresh_token" in result
        user_repo.clear_otp.assert_called_once_with("uid-1")

    @pytest.mark.asyncio
    async def test_verify_mfa_wrong_code(self, service, repos):
        user_repo, _ = repos
        user_repo.get_by_id_with_otp.return_value = {
            "id": "uid-1",
            "phone_number": "+6591234567",
            "mfa_enabled": True,
            "otp_code": "654321",
            "otp_expires_at": datetime.now(timezone.utc) + timedelta(minutes=3),
            "otp_attempts": 0,
        }

        with pytest.raises(HTTPException) as exc:
            await service.verify_mfa(user_id="uid-1", otp_code="000000")
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_verify_mfa_not_enabled(self, service, repos):
        user_repo, _ = repos
        user_repo.get_by_id_with_otp.return_value = {
            "id": "uid-1",
            "phone_number": "+6591234567",
            "mfa_enabled": False,
        }

        with pytest.raises(HTTPException) as exc:
            await service.verify_mfa(user_id="uid-1", otp_code="654321")
        assert exc.value.status_code == 400


class TestToggleMFA:
    @pytest.mark.asyncio
    async def test_enable_mfa(self, service, repos):
        user_repo, _auth_repo = repos
        user_repo.get_by_id.return_value = {
            "id": "uid-1",
            "phone_verified": True,
        }
        user_repo.set_mfa_enabled.return_value = {"id": "uid-1", "mfa_enabled": True}

        result = await service.toggle_mfa("uid-1", True)

        assert result["mfa_enabled"] is True
        user_repo.set_mfa_enabled.assert_called_once_with("uid-1", True)

    @pytest.mark.asyncio
    async def test_enable_mfa_unverified_phone_400(self, service, repos):
        user_repo, _auth_repo = repos
        user_repo.get_by_id.return_value = {
            "id": "uid-1",
            "phone_verified": False,
        }

        with pytest.raises(HTTPException) as exc:
            await service.toggle_mfa("uid-1", True)
        assert exc.value.status_code == 400


class TestLogout:
    @pytest.mark.asyncio
    async def test_revokes_session(self, service, repos):
        _, auth_repo = repos
        jwt = JWTUtil()
        token = jwt.generate_access_token(user_id="uid-1", session_id="sid-1")

        result = await service.logout(token)

        assert result["message"] == "Logged out successfully"
        auth_repo.revoke_session.assert_called_once_with("sid-1")
