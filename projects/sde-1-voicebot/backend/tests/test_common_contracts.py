"""Unit tests for shared common contracts (W5 deliverable)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.contracts.common import (
    ContractModel,
    ErrorEnvelope,
    EventEnvelope,
    SessionState,
    WorkflowState,
)


class DummyPayload(ContractModel):
    name: str
    count: int


def test_contract_model_forbids_extra_fields():
    """ContractModel must strictly reject unexpected fields."""
    with pytest.raises(ValidationError):
        DummyPayload(name="test", count=1, unexpected="extra")


def test_event_envelope_valid():
    """Valid EventEnvelope instances should parse correctly."""
    envelope = EventEnvelope[DummyPayload](
        event_id="evt-1",
        event_type="test.dummy",
        schema_version="1.0",
        session_id="session-123",
        correlation_id="corr-456",
        timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        producer="test-service",
        payload=DummyPayload(name="valid", count=42),
    )
    assert envelope.event_id == "evt-1"
    assert envelope.schema_version == "1.0"
    assert envelope.payload.name == "valid"
    assert envelope.timestamp.tzinfo is not None


@pytest.mark.parametrize(
    "changes",
    [
        {"event_id": ""},
        {"event_id": "   "},
        {"event_type": ""},
        {"schema_version": "2.0"},  # Unsupported version
        {"session_id": ""},
        {"correlation_id": ""},
        {"producer": ""},
        {"timestamp": datetime(2026, 1, 1, 12, 0, 0)},  # Naive (no timezone)
        {"extra_field": "disallowed"},  # Unknown field
    ],
)
def test_event_envelope_invalid_fields(changes):
    """EventEnvelope must reject empty IDs, wrong version, naive time, and extra."""
    base = {
        "event_id": "evt-1",
        "event_type": "test.dummy",
        "schema_version": "1.0",
        "session_id": "session-123",
        "correlation_id": "corr-456",
        "timestamp": datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "producer": "test-service",
        "payload": {"name": "valid", "count": 1},
    }
    base.update(changes)
    with pytest.raises(ValidationError):
        EventEnvelope[DummyPayload].model_validate(base)


def test_error_envelope_valid():
    """Valid ErrorEnvelope should serialize safely with redacted details."""
    err = ErrorEnvelope(
        code="VALIDATION_ERROR",
        message_safe_for_user="Input is not valid.",
        retryable=False,
        correlation_id="corr-789",
        details_redacted={"field": "missing"},
    )
    assert err.code == "VALIDATION_ERROR"
    assert err.retryable is False
    assert err.details_redacted["field"] == "missing"


@pytest.mark.parametrize(
    "changes",
    [
        {"code": ""},
        {"code": "   "},
        {"message_safe_for_user": ""},
        {"retryable": "not_a_bool"},
        {"retryable": 1},  # Booleans must not be integers
        {"correlation_id": ""},
        {"details_redacted": "not_a_dict"},
    ],
)
def test_error_envelope_invalid_fields(changes):
    """ErrorEnvelope must enforce strict types and reject empty strings."""
    base = {
        "code": "ERR_TEST",
        "message_safe_for_user": "Error message",
        "retryable": True,
        "correlation_id": "corr-1",
        "details_redacted": {},
    }
    base.update(changes)
    with pytest.raises(ValidationError):
        ErrorEnvelope.model_validate(base)


def test_session_state_enums():
    """All required SessionState enum values must be present and string-comparable."""
    expected = {
        "created",
        "active",
        "paused",
        "stopping",
        "completed",
        "failed",
        "expired",
    }
    actual = {s.value for s in SessionState}
    assert actual == expected
    assert SessionState.created == "created"


def test_workflow_state_enums():
    """All required WorkflowState enum values must be present."""
    expected = {
        "draft",
        "awaiting_approval",
        "running",
        "paused",
        "succeeded",
        "failed",
        "cancelled",
    }
    actual = {w.value for w in WorkflowState}
    assert actual == expected
    assert WorkflowState.draft == "draft"
