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


def test_transcript_event_valid_segment():
    """TranscriptEvent must accept TranscriptSegment for transcript.segment."""
    from app.contracts.transcription import TranscriptEvent, TranscriptSegment

    seg = TranscriptSegment(
        segment_id="seg-1",
        session_id="sess-1",
        sequence_id=0,
        start_ms=0,
        end_ms=1000,
        text="Hello",
        is_final=True,
    )
    evt = TranscriptEvent(
        event_id="evt-1",
        event_type="transcript.segment",
        schema_version="1.0",
        session_id="sess-1",
        correlation_id="corr-1",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        producer="transcription",
        payload=seg,
    )
    assert evt.event_type == "transcript.segment"
    assert evt.payload.text == "Hello"


def test_transcript_event_rejects_mismatched_payload_or_session():
    """TranscriptEvent must reject mismatched event types or mismatched session IDs."""
    from app.contracts.transcription import TranscriptEvent, TranscriptSegment

    seg = TranscriptSegment(
        segment_id="seg-1",
        session_id="sess-DIFFERENT",
        sequence_id=0,
        start_ms=0,
        end_ms=1000,
        text="Hello",
        is_final=True,
    )
    # Mismatched session ID
    with pytest.raises(ValidationError):
        TranscriptEvent(
            event_id="evt-1",
            event_type="transcript.segment",
            schema_version="1.0",
            session_id="sess-ORIGINAL",
            correlation_id="corr-1",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            producer="transcription",
            payload=seg,
        )

    # Segment payload labeled as transcript.error
    with pytest.raises(ValidationError):
        TranscriptEvent(
            event_id="evt-2",
            event_type="transcript.error",
            schema_version="1.0",
            session_id="sess-DIFFERENT",
            correlation_id="corr-1",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            producer="transcription",
            payload=seg,
        )


def test_mock_session_response_rejects_audio_after_transcript():
    """MockSessionResponse requires audio events to precede transcript events."""
    from app.contracts.sessions import (
        AudioChunkEvent,
        AudioChunkMetadata,
        MockSessionResponse,
    )
    from app.contracts.transcription import TranscriptEvent, TranscriptSegment

    audio_evt = AudioChunkEvent(
        event_id="evt-a",
        event_type="audio.chunk",
        schema_version="1.0",
        session_id="sess-1",
        correlation_id="corr-1",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        producer="audio",
        payload=AudioChunkMetadata(
            sequence_id=0,
            start_ms=0,
            duration_ms=20,
            size_bytes=640,
        ),
    )
    trans_evt = TranscriptEvent(
        event_id="evt-t",
        event_type="transcript.segment",
        schema_version="1.0",
        session_id="sess-1",
        correlation_id="corr-1",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        producer="transcription",
        payload=TranscriptSegment(
            segment_id="seg-1",
            session_id="sess-1",
            sequence_id=0,
            start_ms=0,
            end_ms=1000,
            text="Done",
            is_final=True,
        ),
    )

    # Correct order: audio first, then transcript
    valid_resp = MockSessionResponse(
        session_id="sess-1",
        state="completed",
        mode="mock",
        events=[audio_evt, trans_evt],
    )
    assert len(valid_resp.events) == 2

    # Invalid order: transcript first, then audio
    with pytest.raises(ValidationError):
        MockSessionResponse(
            session_id="sess-1",
            state="completed",
            mode="mock",
            events=[trans_evt, audio_evt],
        )
