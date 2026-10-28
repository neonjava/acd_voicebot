"""Deterministic fake transcriber implementing TranscriptionAdapter."""

from collections.abc import Sequence
from datetime import datetime, timezone

try:
    from app.contracts.audio import AudioChunk
except ImportError:
    from typing import Any

    AudioChunk = Any  # type: ignore

from app.contracts.common import ErrorEnvelope
from app.contracts.transcription import TranscriptEvent, TranscriptSegment


class FakeTranscriber:
    """Deterministic in-memory transcriber without network or API dependencies."""

    def __init__(self, *, timeout_seconds: float = 5.0) -> None:
        if type(timeout_seconds) not in (int, float) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive number")
        self.timeout_seconds = float(timeout_seconds)
        self._cancelled_sessions: set[str] = set()
        self._segment_indices: dict[str, int] = {}

    def health(self) -> str:
        """Return provider health status."""
        return "ready"

    def cancel(self, session_id: str) -> None:
        """Cancel transcription for a session, preventing subsequent output."""
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a nonempty string")
        self._cancelled_sessions.add(session_id)

    def transcribe(
        self,
        chunks: Sequence[AudioChunk],
        *,
        session_id: str,
        correlation_id: str,
        timestamp: datetime,
    ) -> list[TranscriptEvent]:
        """Transcribe audio chunks into timestamped transcript events."""
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a nonempty string")
        if not isinstance(correlation_id, str) or not correlation_id.strip():
            raise ValueError("correlation_id must be a nonempty string")
        if (
            not isinstance(timestamp, datetime)
            or timestamp.tzinfo is None
            or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp)
        ):
            raise ValueError("timestamp must be timezone-aware UTC")

        # Cancellation suppresses subsequent output for that session
        if session_id in self._cancelled_sessions:
            return []

        # Empty input produces empty list
        if not chunks:
            return []

        # Validate chunks consistency and ordering
        expected_seq = chunks[0].sequence_id
        prev_start = -1
        for chunk in chunks:
            if chunk.session_id != session_id:
                # Mixed sessions produce safe error event
                error_payload = ErrorEnvelope(
                    code="TRANSCRIPTION_MIXED_SESSION",
                    message_safe_for_user=(
                        "Audio chunks belong to mixed or mismatched sessions."
                    ),
                    retryable=False,
                    correlation_id=correlation_id,
                    details_redacted={
                        "expected_session": session_id,
                        "received_session": chunk.session_id,
                    },
                )
                return [
                    TranscriptEvent(
                        event_id=f"event-transcript-err-{session_id}",
                        event_type="transcript.error",
                        schema_version="1.0",
                        session_id=session_id,
                        correlation_id=correlation_id,
                        timestamp=timestamp,
                        producer="transcription",
                        payload=error_payload,
                    )
                ]

            if chunk.sequence_id < expected_seq or chunk.start_ms < prev_start:
                # Invalid ordering produces safe error event
                error_payload = ErrorEnvelope(
                    code="TRANSCRIPTION_INVALID_ORDERING",
                    message_safe_for_user="Audio chunks are out of order.",
                    retryable=False,
                    correlation_id=correlation_id,
                    details_redacted={
                        "sequence_id": str(chunk.sequence_id),
                        "start_ms": str(chunk.start_ms),
                    },
                )
                return [
                    TranscriptEvent(
                        event_id=f"event-transcript-err-{session_id}",
                        event_type="transcript.error",
                        schema_version="1.0",
                        session_id=session_id,
                        correlation_id=correlation_id,
                        timestamp=timestamp,
                        producer="transcription",
                        payload=error_payload,
                    )
                ]

            expected_seq = chunk.sequence_id
            prev_start = chunk.start_ms

        # Nonempty valid input produces one final segment
        seg_index = self._segment_indices.get(session_id, 0)
        self._segment_indices[session_id] = seg_index + 1

        start_ms = chunks[0].start_ms
        end_ms = chunks[-1].start_ms + chunks[-1].duration_ms

        segment = TranscriptSegment(
            segment_id=f"{session_id}-segment-{seg_index}",
            session_id=session_id,
            sequence_id=seg_index,
            start_ms=start_ms,
            end_ms=end_ms,
            text="Hello from the mock voicebot.",
            confidence=1.0,
            language="en",
            is_final=True,
        )

        return [
            TranscriptEvent(
                event_id=f"event-transcript-{seg_index}",
                event_type="transcript.segment",
                schema_version="1.0",
                session_id=session_id,
                correlation_id=correlation_id,
                timestamp=timestamp,
                producer="transcription",
                payload=segment,
            )
        ]
