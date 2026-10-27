"""Unit tests for SessionService, in-memory repository, and state machine."""

from datetime import datetime, timezone

import pytest

from app.contracts.common import SessionState
from app.sessions.service import (
    InvalidSessionTransitionError,
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
    # created cannot directly transition to completed
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


def test_run_mock_session_executes_ordered_events(service):
    """run_mock_session emits audio metadata event before transcript event."""
    ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    resp = service.run_mock_session(
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
