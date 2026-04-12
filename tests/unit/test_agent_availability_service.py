"""Unit tests for downstream agent availability checks."""

from app.services.agent_availability_service import AgentAvailabilityService


def test_resolve_base_url_for_known_agent():
    service = AgentAvailabilityService()

    base_url = service.resolve_base_url("program-discovery")

    assert isinstance(base_url, str)
    assert base_url.endswith(":8002")


def test_resolve_base_url_for_unknown_agent_returns_none():
    service = AgentAvailabilityService()

    assert service.resolve_base_url("unknown-agent") is None
