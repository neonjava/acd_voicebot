"""Unit tests for SessionService, in-memory repository, and state machine."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.contracts.common import SessionState
from app.contracts.transcription import TranscriptEvent, TranscriptSegment
from app.sessions.service import (
    InvalidSessionTransitionError,
    MissingDependencyError,
    SessionNotFoundError,
    SessionService,
)


@pytest.fixture
def service():
    srv = SessionService()
    srv.clear()
    return srv


def test_create_and_get_session(service):
    """Session is created with 'created' state and stored in repository."""
    record = service.create_session("sess-001")
    assert record.session_id == "sess-001"
    assert record.state == SessionState.created

    retrieved = service.get_session("sess-001")
    assert retrieved is not None
    assert retrieved.session_id == "sess-001"


def test_valid_session_lifecycle(service):
    """Verify minimum Week 1 transition path: created -> active -> completed."""
    session = service.create_session("sess-lifecycle")
    assert session.state == SessionState.created

    active_sess = service.transition("sess-lifecycle", SessionState.active)
    assert active_sess.state == SessionState.active

    completed_sess = service.transition("sess-lifecycle", SessionState.completed)
    assert completed_sess.state == SessionState.completed


def test_invalid_transition_rejected(service):
    """Attempting an illegal transition raises InvalidSessionTransitionError."""
    service.create_session("sess-invalid")
    with pytest.raises(InvalidSessionTransitionError) as exc_info:
        service.transition("sess-invalid", SessionState.completed)
    assert exc_info.value.from_state == SessionState.created
    assert exc_info.value.to_state == SessionState.completed


def test_terminal_state_has_no_transitions(service):
    """Completed sessions cannot transition further."""
    service.create_session("sess-terminal")
    service.transition("sess-terminal", SessionState.active)
    service.transition("sess-terminal", SessionState.completed)

    with pytest.raises(InvalidSessionTransitionError):
        service.transition("sess-terminal", SessionState.active)


def test_nonexistent_session_raises_not_found(service):
    """Transitioning a nonexistent session ID raises SessionNotFoundError."""
    with pytest.raises(SessionNotFoundError):
        service.transition("sess-does-not-exist", SessionState.active)


def test_run_mock_session_raises_when_dependencies_missing(service):
    """Runtime run_mock_session raises MissingDependencyError when W1/W2 are absent."""
    with patch("importlib.util.find_spec", return_value=None):
        with pytest.raises(MissingDependencyError) as exc_info:
            service.run_mock_session(session_id="sess-missing")
        assert "W1" in exc_info.value.dependency_name


def test_run_synthetic_fixture_session_executes_ordered_events(service):
    """Explicit synthetic fixture session emits audio metadata before transcript."""
    ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    resp = service.run_synthetic_fixture_session(
        session_id="session-demo",
        correlation_id="correlation-demo",
        timestamp=ts,
    )
    assert resp.session_id == "session-demo"
    assert resp.state == "completed"
    assert resp.mode == "mock"
    assert len(resp.events) == 2

    audio_evt = resp.events[0]
    transcript_evt = resp.events[1]

    # Audio chunk event comes first
    assert audio_evt.event_type == "audio.chunk"
    assert audio_evt.producer == "audio"
    assert audio_evt.session_id == "session-demo"
    assert audio_evt.correlation_id == "correlation-demo"
    assert audio_evt.payload.sample_rate_hz == 16000
    assert audio_evt.payload.duration_ms == 1000

    # Transcript event comes second
    assert transcript_evt.event_type == "transcript.segment"
    assert transcript_evt.producer == "transcription"
    assert transcript_evt.session_id == "session-demo"
    assert transcript_evt.correlation_id == "correlation-demo"
    assert transcript_evt.payload.text == "Hello from the mock voicebot."
    assert transcript_evt.payload.is_final is True


def test_run_mock_session_transitions_to_failed_on_missing_dependency(service):
    """Missing upstream dependency transitions stored session to failed."""
    with patch("importlib.util.find_spec", return_value=None):
        with pytest.raises(MissingDependencyError):
            service.run_mock_session(session_id="session-blocked")

    record = service.get_session("session-blocked")
    assert record is not None
    assert record.state == SessionState.failed


def test_run_mock_session_transitions_to_failed_on_producer_failure(service):
    """Runtime producer error transitions stored session to failed."""
    mock_transcriber = MagicMock()
    mock_transcriber.transcribe.side_effect = RuntimeError(
        "Transcriber hardware failed"
    )

    mock_modules = {
        "app.audio": MagicMock(),
        "app.audio.source": MagicMock(
            make_fake_pcm=MagicMock(return_value=bytes(32000))
        ),
        "app.audio.chunker": MagicMock(chunk_pcm=MagicMock(return_value=[])),
        "app.transcription": MagicMock(),
        "app.transcription.mock": MagicMock(
            FakeTranscriber=MagicMock(return_value=mock_transcriber)
        ),
    }

    with (
        patch("importlib.util.find_spec", return_value=MagicMock()),
        patch.dict("sys.modules", mock_modules),
    ):
        with pytest.raises(RuntimeError, match="Transcriber hardware failed"):
            service.run_mock_session(session_id="session-producer-failed")

    record = service.get_session("session-producer-failed")
    assert record is not None
    assert record.state == SessionState.failed


def test_run_mock_session_transitions_to_failed_on_validation_failure(service):
    """Response validation failure transitions stored session to failed."""
    mismatched_event = TranscriptEvent(
        event_id="evt-mismatch",
        event_type="transcript.segment",
        schema_version="1.0",
        session_id="other-session",
        correlation_id="corr-val-fail",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        producer="transcription",
        payload=TranscriptSegment(
            segment_id="seg-1",
            session_id="other-session",
            sequence_id=0,
            start_ms=0,
            end_ms=1000,
            text="Mismatch",
            is_final=True,
        ),
    )

    with pytest.raises(ValidationError):
        service.run_mock_session(
            session_id="session-val-failed",
            correlation_id="corr-val-fail",
            injected_events=[mismatched_event],
        )

    record = service.get_session("session-val-failed")
    assert record is not None
    assert record.state == SessionState.failed


def test_run_mock_session_marks_completed_only_after_validation_succeeds(service):
    """Successful run_mock_session marks session completed after validation."""
    resp = service.run_synthetic_fixture_session(
        session_id="session-completed-check",
    )
    assert resp.state == "completed"
    record = service.get_session("session-completed-check")
    assert record is not None
    assert record.state == SessionState.completed
