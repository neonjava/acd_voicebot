"""In-memory session repository, state transitions, and mock session runner."""

import importlib.util
import uuid
from datetime import datetime, timezone
from typing import Any

from app.contracts.common import ContractModel, SessionState
from app.contracts.sessions import (
    AudioChunkEvent,
    AudioChunkMetadata,
    MockSessionResponse,
    SessionEvent,
)
from app.contracts.transcription import TranscriptEvent, TranscriptSegment

# Documented legal transition table
LEGAL_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.created: {
        SessionState.active,
        SessionState.failed,
        SessionState.expired,
    },
    SessionState.active: {
        SessionState.paused,
        SessionState.stopping,
        SessionState.completed,
        SessionState.failed,
    },
    SessionState.paused: {
        SessionState.active,
        SessionState.stopping,
        SessionState.failed,
        SessionState.expired,
    },
    SessionState.stopping: {SessionState.completed, SessionState.failed},
    SessionState.completed: set(),
    SessionState.failed: set(),
    SessionState.expired: set(),
}


class InvalidSessionTransitionError(Exception):
    """Raised when an illegal session state transition is attempted."""

    def __init__(self, from_state: SessionState, to_state: SessionState) -> None:
        super().__init__(
            f"Cannot transition session from {from_state.value} to {to_state.value}"
        )
        self.from_state = from_state
        self.to_state = to_state


class SessionNotFoundError(Exception):
    """Raised when looking up a session ID that does not exist."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Session not found: {session_id}")
        self.session_id = session_id


class MissingDependencyError(RuntimeError):
    """Raised when a required upstream producer is unavailable on the branch."""

    def __init__(self, dependency_name: str) -> None:
        super().__init__(
            f"Required upstream dependency is unavailable: {dependency_name}"
        )
        self.dependency_name = dependency_name


class SessionRecord(ContractModel):
    """In-memory representation of an active or completed session."""

    session_id: str
    state: SessionState
    created_at: datetime
    updated_at: datetime


class SessionService:
    """Manages session lifecycle in memory and executes mock session runs."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}

    def clear(self) -> None:
        """Clear all sessions (primarily for tests)."""
        self._sessions.clear()

    def create_session(
        self,
        session_id: str | None = None,
        *,
        now: datetime | None = None,
    ) -> SessionRecord:
        """Create a new session in the 'created' state."""
        sid = session_id or f"session-{uuid.uuid4().hex[:12]}"
        timestamp = now or datetime.now(timezone.utc)
        record = SessionRecord(
            session_id=sid,
            state=SessionState.created,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._sessions[sid] = record
        return record

    def get_session(self, session_id: str) -> SessionRecord | None:
        """Retrieve a session by ID."""
        return self._sessions.get(session_id)

    def transition(
        self,
        session_id: str,
        target_state: SessionState,
        *,
        now: datetime | None = None,
    ) -> SessionRecord:
        """Transition a session to a target state, enforcing transition rules."""
        session = self.get_session(session_id)
        if not session:
            raise SessionNotFoundError(session_id)

        allowed = LEGAL_TRANSITIONS.get(session.state, set())
        if target_state not in allowed:
            raise InvalidSessionTransitionError(session.state, target_state)

        updated_time = now or datetime.now(timezone.utc)
        updated_record = SessionRecord(
            session_id=session.session_id,
            state=target_state,
            created_at=session.created_at,
            updated_at=updated_time,
        )
        self._sessions[session_id] = updated_record
        return updated_record

    def run_synthetic_fixture_session(
        self,
        *,
        session_id: str = "session-demo",
        correlation_id: str = "correlation-demo",
        timestamp: datetime | None = None,
    ) -> MockSessionResponse:
        """Explicitly generate the deterministic baseline fixture for contract tests."""
        return self.run_mock_session(
            session_id=session_id,
            correlation_id=correlation_id,
            timestamp=timestamp,
            use_synthetic_fixture=True,
        )

    def run_mock_session(
        self,
        *,
        session_id: str | None = None,
        correlation_id: str | None = None,
        timestamp: datetime | None = None,
        injected_events: list[SessionEvent] | None = None,
        use_synthetic_fixture: bool = False,
    ) -> MockSessionResponse:
        """Execute a complete mock session path: created -> active -> completed.

        In production runtime, calls actual W1 audio and W2 transcription mocks.
        If dependencies are missing, raises MissingDependencyError to report
        blockers instead of silently inventing fake events.
        """
        sid = session_id or f"session-{uuid.uuid4().hex[:12]}"
        cid = correlation_id or f"corr-{uuid.uuid4().hex[:16]}"
        ts = timestamp or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # 1. Create session and transition created -> active
        self.create_session(session_id=sid, now=ts)
        self.transition(sid, SessionState.active, now=ts)

        events: list[SessionEvent] = []

        if injected_events is not None:
            events = list(injected_events)
        elif use_synthetic_fixture:
            # Deterministic baseline fixture only used by explicit fixture tests
            audio_chunk_meta = AudioChunkMetadata(
                sequence_id=0,
                start_ms=0,
                duration_ms=1000,
                sample_rate_hz=16000,
                channels=1,
                size_bytes=32000,
            )
            audio_evt = AudioChunkEvent(
                event_id="event-audio-0",
                event_type="audio.chunk",
                schema_version="1.0",
                session_id=sid,
                correlation_id=cid,
                timestamp=ts,
                producer="audio",
                payload=audio_chunk_meta,
            )
            events.append(audio_evt)

            transcript_segment = TranscriptSegment(
                segment_id=f"{sid}-segment-0",
                session_id=sid,
                sequence_id=0,
                start_ms=0,
                end_ms=1000,
                text="Hello from the mock voicebot.",
                confidence=1.0,
                language="en",
                is_final=True,
            )
            transcript_evt = TranscriptEvent(
                event_id="event-transcript-0",
                event_type="transcript.segment",
                schema_version="1.0",
                session_id=sid,
                correlation_id=cid,
                timestamp=ts,
                producer="transcription",
                payload=transcript_segment,
            )
            events.append(transcript_evt)
        else:
            # Runtime path: require actual modules or report missing dependency
            if (
                importlib.util.find_spec("app.audio.source") is None
                or importlib.util.find_spec("app.audio.chunker") is None
            ):
                raise MissingDependencyError("app.audio (W1)")

            if importlib.util.find_spec("app.transcription.mock") is None:
                raise MissingDependencyError("app.transcription (W2)")

            # Import directly without broad try-except to avoid masking bugs
            from app.audio.chunker import chunk_pcm
            from app.audio.source import make_fake_pcm
            from app.transcription.mock import FakeTranscriber

            pcm_bytes = make_fake_pcm(duration_ms=1000)
            audio_chunks = chunk_pcm(pcm_bytes, session_id=sid, chunk_ms=20)

            audio_chunk_meta = AudioChunkMetadata(
                sequence_id=0,
                start_ms=0,
                duration_ms=1000,
                sample_rate_hz=16000,
                channels=1,
                size_bytes=len(pcm_bytes),
            )
            audio_evt = AudioChunkEvent(
                event_id="event-audio-0",
                event_type="audio.chunk",
                schema_version="1.0",
                session_id=sid,
                correlation_id=cid,
                timestamp=ts,
                producer="audio",
                payload=audio_chunk_meta,
            )
            events.append(audio_evt)

            transcriber = FakeTranscriber()
            transcript_events: list[Any] = transcriber.transcribe(
                audio_chunks,
                session_id=sid,
                correlation_id=cid,
                timestamp=ts,
            )
            events.extend(transcript_events)

        # Transition active -> completed
        self.transition(sid, SessionState.completed, now=ts)

        return MockSessionResponse(
            session_id=sid,
            state="completed",
            mode="mock",
            events=events,
        )


session_service = SessionService()
