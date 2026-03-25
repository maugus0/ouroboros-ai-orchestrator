"""Tests for trace ID generation."""

import uuid

from app.utils.trace_id import generate_trace_id


def test_trace_id_is_valid_uuid():
    tid = generate_trace_id()
    parsed = uuid.UUID(tid, version=4)
    assert str(parsed) == tid
