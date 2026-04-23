"""Unit tests for student-profile client internal token behavior."""

import pytest

from app.clients.student_profile_client import StudentProfileClient
from app.config import settings


class _StubIssuer:
    def __init__(self):
        self.calls = []

    def resolve_audience(self, service_name: str) -> str:
        self.calls.append(("resolve_audience", service_name))
        return "ouroboros.student-profile"

    def build_bearer_token(self, *, sub: str, aud: str, sid=None, trace_id=None, _extra_claims=None):
        self.calls.append(("build_bearer_token", sub, aud, sid, trace_id))
        return "Bearer internal-token"


@pytest.mark.asyncio
async def test_get_profile_status_uses_internal_token_when_enabled(monkeypatch):
    stub_issuer = _StubIssuer()
    client = StudentProfileClient(internal_token_issuer=stub_issuer)

    monkeypatch.setattr(settings, "INTERNAL_TOKEN_ENABLED", True)

    captured = {}

    async def _stub_request(_self, method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured.update(kwargs)
        return {"data": {"completed": False}}

    monkeypatch.setattr(StudentProfileClient, "request", _stub_request)

    await client.get_profile_status(user_id="user-1", session_id="chat-1", trace_id="trace-1")

    assert captured["authorization"] == "Bearer internal-token"
    assert ("resolve_audience", "student-profile") in stub_issuer.calls
    assert ("build_bearer_token", "user-1", "ouroboros.student-profile", "chat-1", "trace-1") in stub_issuer.calls


@pytest.mark.asyncio
async def test_explicit_authorization_takes_precedence(monkeypatch):
    stub_issuer = _StubIssuer()
    client = StudentProfileClient(internal_token_issuer=stub_issuer)

    monkeypatch.setattr(settings, "INTERNAL_TOKEN_ENABLED", True)

    captured = {}

    async def _stub_request(_self, _method, _path, **kwargs):
        captured.update(kwargs)
        return {"data": {"completed": False}}

    monkeypatch.setattr(StudentProfileClient, "request", _stub_request)

    await client.get_profile_status(user_id="user-1", authorization="Bearer upstream-token")

    assert captured["authorization"] == "Bearer upstream-token"
    assert not stub_issuer.calls


@pytest.mark.asyncio
async def test_get_profile_uses_internal_token_when_enabled(monkeypatch):
    stub_issuer = _StubIssuer()
    client = StudentProfileClient(internal_token_issuer=stub_issuer)

    monkeypatch.setattr(settings, "INTERNAL_TOKEN_ENABLED", True)

    captured = {}

    async def _stub_request(_self, method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured.update(kwargs)
        return {"data": {"id": "profile-1"}}

    monkeypatch.setattr(StudentProfileClient, "request", _stub_request)

    await client.get_profile("profile-1", user_id="user-1", session_id="chat-1", trace_id="trace-1")

    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/profiles/profile-1"
    assert captured["authorization"] == "Bearer internal-token"
