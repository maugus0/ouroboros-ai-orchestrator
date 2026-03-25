"""Tests for custom exception classes."""

from app.utils.exceptions import (
    AgentCallError,
    AuthenticationError,
    DatabaseError,
    NotFoundError,
    ValidationError,
    WorkflowError,
)


def test_database_error():
    err = DatabaseError("connection lost")
    assert err.status_code == 500
    assert "connection lost" in str(err)


def test_authentication_error():
    err = AuthenticationError()
    assert err.status_code == 401


def test_not_found_error():
    err = NotFoundError("Chat")
    assert err.status_code == 404
    assert "Chat not found" in err.message


def test_validation_error():
    err = ValidationError("bad input")
    assert err.status_code == 422


def test_agent_call_error():
    err = AgentCallError("eligibility_engine", "timeout")
    assert err.status_code == 502
    assert "eligibility_engine" in err.message


def test_workflow_error():
    err = WorkflowError()
    assert err.status_code == 409
