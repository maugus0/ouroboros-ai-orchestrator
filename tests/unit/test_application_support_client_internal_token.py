"""Unit tests for application-support client internal token behavior."""

import pytest

from app.clients.application_support_client import ApplicationSupportClient
from app.config import settings


class _StubIssuer:
    def __init__(self):
        self.calls = []

    def resolve_audience(self, service_name: str) -> str:
        self.calls.append(("resolve_audience", service_name))
        return "ouroboros.application-support"

    def build_bearer_token(self, *, sub: str, aud: str, sid=None, trace_id=None, extra_claims=None):
        self.calls.append(("build_bearer_token", sub, aud, sid, trace_id, extra_claims))
        return "Bearer internal-token"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "expected_method", "expected_path"),
    [
        ("generate_sop", "POST", "/api/v1/applications/generate-sop"),
        ("generate_cover_letter", "POST", "/api/v1/applications/generate-cover-letter"),
        ("create_checklist", "POST", "/api/v1/applications/checklist"),
        ("sync_deadlines", "POST", "/api/v1/applications/deadlines/sync"),
    ],
)
async def test_application_support_mutating_methods_use_internal_token(
    monkeypatch, method_name, expected_method, expected_path
):
    stub_issuer = _StubIssuer()
    client = ApplicationSupportClient(internal_token_issuer=stub_issuer)
    monkeypatch.setattr(settings, "INTERNAL_TOKEN_ENABLED", True)

    captured = {}

    async def _stub_request(_self, method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured.update(kwargs)
        return {"data": {"ok": True}}

    monkeypatch.setattr(ApplicationSupportClient, "request", _stub_request)

    await getattr(client, method_name)("user-1", {"user_id": "user-1"}, session_id="chat-1", trace_id="trace-1")

    assert captured["method"] == expected_method
    assert captured["path"] == expected_path
    assert captured["authorization"] == "Bearer internal-token"
    assert ("resolve_audience", "application-support") in stub_issuer.calls
    assert (
        "build_bearer_token",
        "user-1",
        "ouroboros.application-support",
        "chat-1",
        "trace-1",
        None,
    ) in stub_issuer.calls


@pytest.mark.asyncio
async def test_list_deadlines_passes_window_and_internal_token(monkeypatch):
    stub_issuer = _StubIssuer()
    client = ApplicationSupportClient(internal_token_issuer=stub_issuer)
    monkeypatch.setattr(settings, "INTERNAL_TOKEN_ENABLED", True)

    captured = {}

    async def _stub_request(_self, method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured.update(kwargs)
        return {"data": []}

    monkeypatch.setattr(ApplicationSupportClient, "request", _stub_request)

    await client.list_deadlines("user-1", approaching_days=45, session_id="chat-1", trace_id="trace-1")

    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/applications/deadlines/user-1"
    assert captured["params"] == {"approaching_days": 45}
    assert captured["authorization"] == "Bearer internal-token"


@pytest.mark.asyncio
async def test_explicit_authorization_takes_precedence(monkeypatch):
    stub_issuer = _StubIssuer()
    client = ApplicationSupportClient(internal_token_issuer=stub_issuer)
    monkeypatch.setattr(settings, "INTERNAL_TOKEN_ENABLED", True)

    captured = {}

    async def _stub_request(_self, _method, _path, **kwargs):
        captured.update(kwargs)
        return {"data": {"ok": True}}

    monkeypatch.setattr(ApplicationSupportClient, "request", _stub_request)

    await client.generate_sop("user-1", {"user_id": "user-1"}, authorization="Bearer upstream-token")

    assert captured["authorization"] == "Bearer upstream-token"
    assert not stub_issuer.calls
