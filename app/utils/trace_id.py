"""Trace ID generation for distributed request tracing across agent services."""

import uuid

import structlog


def generate_trace_id() -> str:
    """Generate a UUID-v4 trace ID for correlating logs across services."""
    return str(uuid.uuid4())


def bind_trace_id(trace_id: str | None = None) -> str:
    """Bind a trace ID to the structlog context so every log line includes it."""
    tid = trace_id or generate_trace_id()
    structlog.contextvars.bind_contextvars(trace_id=tid)
    return tid


def clear_trace_context() -> None:
    """Clear trace context at the end of a request."""
    structlog.contextvars.unbind_contextvars("trace_id")
