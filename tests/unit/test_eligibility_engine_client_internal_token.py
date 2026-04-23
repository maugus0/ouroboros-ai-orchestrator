"""Unit tests for eligibility-engine client internal token behavior."""

import pytest

from app.clients.eligibility_engine_client import EligibilityEngineClient
from app.config import settings


class _StubIssuer:
    def __init__(self):
        self.calls = []

    def resolve_audience(self, service_name: str) -> str:
        self.calls.append(("resolve_audience", service_name))
        return "ouroboros.eligibility-engine"

    def build_bearer_token(self, *, sub: str, aud: str, sid=None, trace_id=None, extra_claims=None):
        self.calls.append(("build_bearer_token", sub, aud, sid, trace_id, extra_claims))
        return "Bearer internal-token"


@pytest.mark.asyncio
async def test_evaluate_batch_uses_internal_token(monkeypatch):
    stub_issuer = _StubIssuer()
    client = EligibilityEngineClient(internal_token_issuer=stub_issuer)
    monkeypatch.setattr(settings, "INTERNAL_TOKEN_ENABLED", True)

    captured = {}

    async def _stub_request(_self, method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured.update(kwargs)
        return {"data": {"count": 0, "results": []}}

    monkeypatch.setattr(EligibilityEngineClient, "request", _stub_request)

    await client.evaluate_batch(
        user_id="user-1",
        payload={"user_id": "user-1", "user_profile": {}, "evaluations": []},
        trace_id="trace-1",
        session_id="session-1",
    )

    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/eligibility/evaluate/batch"
    assert captured["authorization"] == "Bearer internal-token"
    assert ("resolve_audience", "eligibility-engine") in stub_issuer.calls


@pytest.mark.asyncio
async def test_explicit_authorization_takes_precedence(monkeypatch):
    stub_issuer = _StubIssuer()
    client = EligibilityEngineClient(internal_token_issuer=stub_issuer)
    monkeypatch.setattr(settings, "INTERNAL_TOKEN_ENABLED", True)

    captured = {}

    async def _stub_request(_self, _method, _path, **kwargs):
        captured.update(kwargs)
        return {"data": {"count": 0, "results": []}}

    monkeypatch.setattr(EligibilityEngineClient, "request", _stub_request)

    await client.evaluate_batch(
        user_id="user-1",
        payload={"user_id": "user-1", "user_profile": {}, "evaluations": []},
        authorization="Bearer upstream-token",
    )

    assert captured["authorization"] == "Bearer upstream-token"
    assert not stub_issuer.calls
