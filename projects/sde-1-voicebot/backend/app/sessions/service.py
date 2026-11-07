"""In-memory session repository, state transitions, and mock session runner."""

import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.contracts.common import ContractModel, SessionState
from app.contracts.sessions import (
    AudioChunkEvent,
    AudioChunkMetadata,
    IdempotencyRecord,
    MockSessionResponse,
    SessionEvent,
    SessionStateResponse,
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
        SessionState.expired,
    },
    SessionState.paused: {
        SessionState.active,
        SessionState.stopping,
        SessionState.completed,
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


class SessionAlreadyExistsError(Exception):
    """Raised when creating a session with an ID that already exists."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Session already exists: {session_id}")
        self.session_id = session_id


class SessionExpiredError(Exception):
    """Raised when performing an action on an expired session."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Session has expired: {session_id}")
        self.session_id = session_id


class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused for a different session or action."""

    def __init__(
        self,
        key: str,
        cached_action: str,
        cached_session_id: str,
        requested_action: str,
        requested_session_id: str,
    ) -> None:
        super().__init__(
            f"Idempotency key '{key}' was already used for action '{cached_action}' "
            f"and session '{cached_session_id}'"
        )
        self.key = key
        self.cached_action = cached_action
        self.cached_session_id = cached_session_id
        self.requested_action = requested_action
        self.requested_session_id = requested_session_id


class MissingDependencyError(RuntimeError):
    """Raised when a required upstream producer is unavailable on the branch."""

    def __init__(self, dependency_name: str) -> None:
        super().__init__(
            f"Required upstream dependency is unavailable: {dependency_name}"
        )
        self.dependency_name = dependency_name


class SessionRecord(ContractModel):
    """In-memory representation of an active, paused, or completed session."""

    session_id: str
    state: SessionState
    mode: str = "mock"
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None


class SessionService:
    """Manages session lifecycle in memory and executes mock session runs."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._session_events: dict[str, list[SessionEvent]] = {}
        self._idempotency_cache: dict[str, IdempotencyRecord] = {}

    def clear(self) -> None:
        """Clear all sessions and caches (primarily for test isolation)."""
        self._sessions.clear()
        self._session_events.clear()
        self._idempotency_cache.clear()

    def create_session(
        self,
        session_id: str | None = None,
        *,
        initial_state: SessionState = SessionState.created,
        now: datetime | None = None,
        ttl_seconds: int | None = None,
    ) -> SessionRecord:
        """Create a new session in 'created' or 'active' state with TTL expiry."""
        sid = session_id or f"session-{uuid.uuid4().hex[:12]}"
        if sid in self._sessions:
            raise SessionAlreadyExistsError(sid)

        timestamp = now or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        effective_ttl = (
            ttl_seconds if ttl_seconds is not None else settings.session_ttl_seconds
        )
        expires_at = timestamp + timedelta(seconds=effective_ttl)

        record = SessionRecord(
            session_id=sid,
            state=initial_state,
            mode="mock",
            created_at=timestamp,
            updated_at=timestamp,
            expires_at=expires_at,
        )
        self._sessions[sid] = record
        self._session_events[sid] = []
        return record

    def get_session(
        self,
        session_id: str,
        *,
        check_expiry: bool = True,
        now: datetime | None = None,
    ) -> SessionRecord | None:
        """Retrieve a session by ID, automatically evaluating TTL expiry."""
        record = self._sessions.get(session_id)
        if not record:
            return None

        if check_expiry and record.expires_at is not None:
            current_time = now or datetime.now(timezone.utc)
            if current_time.tzinfo is None:
                current_time = current_time.replace(tzinfo=timezone.utc)

            # Check if active/paused/created session has exceeded TTL
            if current_time >= record.expires_at and record.state in (
                SessionState.created,
                SessionState.active,
                SessionState.paused,
            ):
                updated_record = SessionRecord(
                    session_id=record.session_id,
                    state=SessionState.expired,
                    mode=record.mode,
                    created_at=record.created_at,
                    updated_at=current_time,
                    expires_at=record.expires_at,
                )
                self._sessions[session_id] = updated_record
                return updated_record

        return record

    def transition(
        self,
        session_id: str,
        target_state: SessionState,
        *,
        now: datetime | None = None,
    ) -> SessionRecord:
        """Transition a session to a target state, enforcing transition rules."""
        session = self.get_session(session_id, check_expiry=False)
        if not session:
            raise SessionNotFoundError(session_id)

        # Re-check expiry before executing transition
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)

        if (
            session.expires_at is not None
            and current_time >= session.expires_at
            and target_state != SessionState.expired
            and session.state
            in (
                SessionState.created,
                SessionState.active,
                SessionState.paused,
            )
        ):
            self.transition(session_id, SessionState.expired, now=current_time)
            raise SessionExpiredError(session_id)

        allowed = LEGAL_TRANSITIONS.get(session.state, set())
        if target_state not in allowed:
            raise InvalidSessionTransitionError(session.state, target_state)

        updated_record = SessionRecord(
            session_id=session.session_id,
            state=target_state,
            mode=session.mode,
            created_at=session.created_at,
            updated_at=current_time,
            expires_at=session.expires_at,
        )
        self._sessions[session_id] = updated_record
        return updated_record

    def pause_session(
        self, session_id: str, *, now: datetime | None = None
    ) -> SessionRecord:
        """Pause an active session. Idempotent if already paused."""
        session = self.get_session(session_id, now=now)
        if not session:
            raise SessionNotFoundError(session_id)
        if session.state == SessionState.paused:
            return session
        if session.state == SessionState.expired:
            raise SessionExpiredError(session_id)
        return self.transition(session_id, SessionState.paused, now=now)

    def resume_session(
        self, session_id: str, *, now: datetime | None = None
    ) -> SessionRecord:
        """Resume a paused session to active. Idempotent if already active."""
        session = self.get_session(session_id, now=now)
        if not session:
            raise SessionNotFoundError(session_id)
        if session.state == SessionState.active:
            return session
        if session.state == SessionState.expired:
            raise SessionExpiredError(session_id)
        return self.transition(session_id, SessionState.active, now=now)

    def stop_session(
        self, session_id: str, *, now: datetime | None = None
    ) -> SessionRecord:
        """Stop a session and mark it completed. Idempotent if already completed."""
        session = self.get_session(session_id, now=now)
        if not session:
            raise SessionNotFoundError(session_id)
        if session.state == SessionState.completed:
            return session
        if session.state == SessionState.expired:
            raise SessionExpiredError(session_id)

        current_time = now or datetime.now(timezone.utc)
        return self.transition(session_id, SessionState.completed, now=current_time)

    def expire_session(
        self, session_id: str, *, now: datetime | None = None
    ) -> SessionRecord:
        """Explicitly transition a non-terminal session to expired."""
        session = self.get_session(session_id, check_expiry=False)
        if not session:
            raise SessionNotFoundError(session_id)
        if session.state == SessionState.expired:
            return session
        return self.transition(session_id, SessionState.expired, now=now)

    def add_event(self, session_id: str, event: SessionEvent) -> None:
        """Append an event to the session's ordered event buffer."""
        if event.session_id != session_id:
            raise ValueError(
                f"Event session_id '{event.session_id}' does not match "
                f"target session '{session_id}'"
            )
        if session_id not in self._session_events:
            self._session_events[session_id] = []

        events = self._session_events[session_id]
        if len(events) >= settings.max_events_per_session:
            raise ValueError(
                f"Session event limit ({settings.max_events_per_session}) reached"
            )
        events.append(event)

    def get_events(
        self,
        session_id: str,
        *,
        from_sequence: int = 0,
        limit: int = 100,
    ) -> list[SessionEvent]:
        """Retrieve ordered events for a session using session-wide index and limit."""
        if session_id not in self._sessions:
            raise SessionNotFoundError(session_id)

        all_events = self._session_events.get(session_id, [])
        return all_events[from_sequence : from_sequence + limit]

    # --- Idempotency helpers ---

    def get_idempotent_result(
        self,
        idempotency_key: str,
        action: str,
        session_id: str | None = None,
    ) -> IdempotencyRecord | None:
        """Look up cached response and verify action and session_id match."""
        cached = self._idempotency_cache.get(idempotency_key)
        if not cached:
            return None

        if session_id is not None and cached.session_id != session_id:
            raise IdempotencyConflictError(
                idempotency_key,
                cached.action,
                cached.session_id,
                action,
                session_id,
            )

        if cached.action != action:
            raise IdempotencyConflictError(
                idempotency_key,
                cached.action,
                cached.session_id,
                action,
                session_id or "",
            )

        return cached

    def record_idempotent_result(
        self,
        idempotency_key: str,
        action: str,
        session_id: str,
        status_code: int,
        response_body: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> IdempotencyRecord:
        """Cache response data for a given idempotency key."""
        timestamp = now or datetime.now(timezone.utc)
        record = IdempotencyRecord(
            idempotency_key=idempotency_key,
            action=action,
            session_id=session_id,
            status_code=status_code,
            response_body=response_body,
            created_at=timestamp,
        )
        self._idempotency_cache[idempotency_key] = record
        return record

    def to_state_response(self, record: SessionRecord) -> SessionStateResponse:
        """Convert in-memory SessionRecord to standard SessionStateResponse."""
        return SessionStateResponse(
            session_id=record.session_id,
            state=record.state,
            mode="mock",
            created_at=record.created_at,
            updated_at=record.updated_at,
            expires_at=record.expires_at,
        )

    # --- Week 1 Compatibility Run Mock Session ---

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
        """Execute a complete mock session path: created -> active -> completed."""
        sid = session_id or f"session-{uuid.uuid4().hex[:12]}"
        cid = correlation_id or f"corr-{uuid.uuid4().hex[:16]}"
        ts = timestamp or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # 1. Create session and transition created -> active
        self.create_session(session_id=sid, now=ts)
        self.transition(sid, SessionState.active, now=ts)

        try:
            events: list[SessionEvent] = []

            if injected_events is not None:
                events = list(injected_events)
            elif use_synthetic_fixture:
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
                if (
                    importlib.util.find_spec("app.audio.source") is None
                    or importlib.util.find_spec("app.audio.chunker") is None
                ):
                    raise MissingDependencyError("app.audio (W1)")

                if importlib.util.find_spec("app.transcription.mock") is None:
                    raise MissingDependencyError("app.transcription (W2)")

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

            # Build and validate response FIRST before marking completed
            response = MockSessionResponse(
                session_id=sid,
                state="completed",
                mode="mock",
                events=events,
            )

            # Store events into buffer
            self._session_events[sid] = list(events)

            self.transition(sid, SessionState.completed, now=ts)
            return response
        except Exception:
            self.transition(sid, SessionState.failed, now=ts)
            raise


session_service = SessionService()
