"""Tests for transcription contracts (TranscriptSegment and TranscriptEvent)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.common import ErrorEnvelope
from app.contracts.transcription import TranscriptEvent, TranscriptSegment

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "transcript_event.json"


def _make_valid_segment(**overrides) -> TranscriptSegment:
    base = {
        "segment_id": "seg-1",
        "session_id": "sess-1",
        "sequence_id": 0,
        "start_ms": 0,
        "end_ms": 1000,
        "text": "Hello world.",
        "confidence": 0.95,
        "language": "en",
        "is_final": True,
    }
    base.update(overrides)
    return TranscriptSegment(**base)


def _make_valid_event(**overrides) -> TranscriptEvent:
    base = {
        "event_id": "event-1",
        "event_type": "transcript.segment",
        "schema_version": "1.0",
        "session_id": "sess-1",
        "correlation_id": "corr-1",
        "timestamp": datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        "producer": "transcription",
        "payload": _make_valid_segment(),
    }
    base.update(overrides)
    return TranscriptEvent(**base)


class TestTranscriptSegmentContracts:
    """Validation test suite for TranscriptSegment."""

    def test_valid_segment_instantiation(self):
        seg = _make_valid_segment()
        assert seg.segment_id == "seg-1"
        assert seg.session_id == "sess-1"
        assert seg.sequence_id == 0
        assert seg.start_ms == 0
        assert seg.end_ms == 1000
        assert seg.text == "Hello world."
        assert seg.confidence == 0.95
        assert seg.language == "en"
        assert seg.is_final is True

    def test_default_values(self):
        seg = TranscriptSegment(
            segment_id="seg-default",
            session_id="sess-default",
            sequence_id=0,
            start_ms=10,
            end_ms=20,
            text="Default check",
        )
        assert seg.language == "en"
        assert seg.is_final is True
        assert seg.confidence is None

    @pytest.mark.parametrize(
        "missing_field",
        ["segment_id", "session_id", "sequence_id", "start_ms", "end_ms", "text"],
    )
    def test_missing_required_fields(self, missing_field: str):
        payload = {
            "segment_id": "seg-1",
            "session_id": "sess-1",
            "sequence_id": 0,
            "start_ms": 0,
            "end_ms": 100,
            "text": "Hello",
        }
        del payload[missing_field]
        with pytest.raises(ValidationError):
            TranscriptSegment(**payload)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("segment_id", ""),
            ("segment_id", "   "),
            ("session_id", ""),
            ("session_id", "   "),
            ("text", ""),
            ("text", "   "),
            ("language", ""),
            ("language", "   "),
        ],
    )
    def test_blank_or_empty_strings_rejected(self, field: str, value: str):
        with pytest.raises(ValidationError):
            _make_valid_segment(**{field: value})

    @pytest.mark.parametrize(
        "field,value",
        [
            ("sequence_id", True),
            ("sequence_id", 1.5),
            ("sequence_id", "0"),
            ("sequence_id", -1),
            ("start_ms", False),
            ("start_ms", 12.3),
            ("start_ms", "100"),
            ("start_ms", -10),
            ("end_ms", True),
            ("end_ms", 45.6),
            ("end_ms", "200"),
            ("end_ms", -5),
        ],
    )
    def test_strict_integer_requirements(self, field: str, value: object):
        with pytest.raises(ValidationError):
            _make_valid_segment(**{field: value})

    @pytest.mark.parametrize("value", [0, 1, "true", "false", None, 1.0])
    def test_strict_boolean_for_is_final(self, value: object):
        with pytest.raises(ValidationError):
            _make_valid_segment(is_final=value)

    def test_timestamp_range_validation(self):
        # end_ms == start_ms is valid (zero-length instant)
        seg = _make_valid_segment(start_ms=100, end_ms=100)
        assert seg.start_ms == seg.end_ms

        # end_ms < start_ms is invalid
        with pytest.raises(ValidationError, match="cannot be less than start_ms"):
            _make_valid_segment(start_ms=200, end_ms=100)

    @pytest.mark.parametrize("conf", [0.0, 1.0, 0.5, None])
    def test_valid_confidence_values(self, conf: float | None):
        seg = _make_valid_segment(confidence=conf)
        assert seg.confidence == conf

    @pytest.mark.parametrize(
        "conf",
        [-0.01, 1.01, float("nan"), float("inf"), float("-inf")],
    )
    def test_invalid_confidence_values(self, conf: float):
        with pytest.raises(ValidationError):
            _make_valid_segment(confidence=conf)

    def test_unknown_fields_forbidden(self):
        with pytest.raises(ValidationError, match="extra"):
            _make_valid_segment(unexpected="field")


class TestTranscriptEventContracts:
    """Validation test suite for TranscriptEvent."""

    def test_valid_segment_event(self):
        event = _make_valid_event()
        assert event.event_type == "transcript.segment"
        assert event.producer == "transcription"
        assert event.schema_version == "1.0"
        assert isinstance(event.payload, TranscriptSegment)

    def test_valid_error_event(self):
        err = ErrorEnvelope(
            code="TRANSCRIPTION_FAILED",
            message_safe_for_user="Speech service failed.",
            retryable=False,
            correlation_id="corr-err-1",
            details_redacted={},
        )
        event = TranscriptEvent(
            event_id="event-err-1",
            event_type="transcript.error",
            schema_version="1.0",
            session_id="sess-1",
            correlation_id="corr-err-1",
            timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            producer="transcription",
            payload=err,
        )
        assert event.event_type == "transcript.error"
        assert isinstance(event.payload, ErrorEnvelope)

    def test_payload_pairing_mismatch_segment_with_error_payload(self):
        err = ErrorEnvelope(
            code="TRANSCRIPTION_FAILED",
            message_safe_for_user="Error",
            retryable=False,
            correlation_id="corr-1",
        )
        with pytest.raises(ValidationError, match="payload must be TranscriptSegment"):
            _make_valid_event(event_type="transcript.segment", payload=err)

    def test_payload_pairing_mismatch_error_with_segment_payload(self):
        seg = _make_valid_segment()
        with pytest.raises(ValidationError, match="payload must be ErrorEnvelope"):
            _make_valid_event(event_type="transcript.error", payload=seg)

    def test_session_id_mismatch_raises(self):
        seg = _make_valid_segment(session_id="session-different")
        with pytest.raises(ValidationError, match="must match envelope session_id"):
            _make_valid_event(session_id="session-envelope", payload=seg)

    def test_correlation_id_mismatch_for_error_raises(self):
        err = ErrorEnvelope(
            code="TRANSCRIPTION_FAILED",
            message_safe_for_user="Error",
            retryable=False,
            correlation_id="corr-different",
        )
        with pytest.raises(ValidationError, match="must match envelope correlation_id"):
            _make_valid_event(
                event_type="transcript.error",
                correlation_id="corr-envelope",
                payload=err,
            )

    def test_incompatible_schema_version_raises(self):
        with pytest.raises(ValidationError):
            _make_valid_event(schema_version="2.0")

    def test_invalid_producer_raises(self):
        with pytest.raises(ValidationError):
            _make_valid_event(producer="audio")

    def test_naive_timestamp_raises(self):
        naive_dt = datetime(2026, 1, 1, 0, 0, 0)
        with pytest.raises(ValidationError, match="timezone-aware"):
            _make_valid_event(timestamp=naive_dt)

    def test_non_utc_timestamp_raises(self):
        from datetime import timedelta

        non_utc = datetime(
            2026, 1, 1, 5, 30, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))
        )
        with pytest.raises(ValidationError, match="UTC offset"):
            _make_valid_event(timestamp=non_utc)


class TestTranscriptEventFixture:
    """Verify shared transcript_event.json fixture against contract."""

    def test_fixture_file_exists_and_matches_spec(self):
        assert FIXTURE_PATH.is_file(), f"Fixture file not found: {FIXTURE_PATH}"
        data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

        event = TranscriptEvent.model_validate(data)
        assert event.event_id == "event-transcript-0"
        assert event.event_type == "transcript.segment"
        assert event.schema_version == "1.0"
        assert event.session_id == "session-demo"
        assert event.correlation_id == "correlation-demo"
        assert event.producer == "transcription"

        assert isinstance(event.payload, TranscriptSegment)
        assert event.payload.segment_id == "session-demo-segment-0"
        assert event.payload.session_id == "session-demo"
        assert event.payload.sequence_id == 0
        assert event.payload.start_ms == 0
        assert event.payload.end_ms == 1000
        assert event.payload.text == "Hello from the mock voicebot."
        assert event.payload.confidence == 1.0
        assert event.payload.language == "en"
        assert event.payload.is_final is True
