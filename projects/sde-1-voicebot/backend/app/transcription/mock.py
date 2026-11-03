"""Deterministic fake transcriber implementing TranscriptionAdapter."""

from collections.abc import Sequence
from datetime import datetime, timezone

from app.contracts.audio import AudioChunk
from app.contracts.common import ErrorEnvelope
from app.contracts.transcription import TranscriptEvent, TranscriptSegment


class FakeTranscriber:
    """Deterministic in-memory transcriber without network or API dependencies."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        failure_mode: str | None = None,
        failures_before_success: int = 0,
        custom_texts: Sequence[str] | None = None,
    ) -> None:
        if type(timeout_seconds) not in (int, float) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive number")
        if failures_before_success < 0:
            raise ValueError("failures_before_success must be nonnegative")

        self.timeout_seconds = float(timeout_seconds)
        self.failure_mode = failure_mode
        self.failures_before_success = failures_before_success
        self.custom_texts = list(custom_texts) if custom_texts is not None else None

        self._cancelled_sessions: set[str] = set()
        self._segment_indices: dict[str, int] = {}
        self._call_count: int = 0

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

        self._call_count += 1

        # Check simulated failure modes for testing bounded retries & timeouts
        if (
            self.failures_before_success > 0
            and self._call_count <= self.failures_before_success
        ):
            return self._produce_simulated_failure(
                session_id,
                correlation_id,
                timestamp,
                mode=self.failure_mode or "temporary_error",
            )
        elif self.failure_mode is not None and self.failures_before_success == 0:
            return self._produce_simulated_failure(
                session_id, correlation_id, timestamp, mode=self.failure_mode
            )

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

        text = "Hello from the mock voicebot."
        if self.custom_texts:
            text = self.custom_texts[seg_index % len(self.custom_texts)]

        segment = TranscriptSegment(
            segment_id=f"{session_id}-segment-{seg_index}",
            session_id=session_id,
            sequence_id=seg_index,
            start_ms=start_ms,
            end_ms=end_ms,
            text=text,
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

    def _produce_simulated_failure(
        self,
        session_id: str,
        correlation_id: str,
        timestamp: datetime,
        *,
        mode: str,
    ) -> list[TranscriptEvent]:
        """Produce deterministic simulated failure for testing."""
        if mode == "timeout":
            raise TimeoutError("Simulated transcriber timeout")

        if mode == "temporary_error":
            payload = ErrorEnvelope(
                code="TRANSCRIPTION_TEMPORARY_ERROR",
                message_safe_for_user="Temporary transcription provider failure.",
                retryable=True,
                correlation_id=correlation_id,
                details_redacted={"mode": "simulated_temporary"},
            )
        elif mode == "permanent_error":
            payload = ErrorEnvelope(
                code="TRANSCRIPTION_PERMANENT_ERROR",
                message_safe_for_user="Permanent transcription provider failure.",
                retryable=False,
                correlation_id=correlation_id,
                details_redacted={"mode": "simulated_permanent"},
            )
        else:
            payload = ErrorEnvelope(
                code="TRANSCRIPTION_ERROR",
                message_safe_for_user="Transcription failure occurred.",
                retryable=False,
                correlation_id=correlation_id,
                details_redacted={"mode": mode},
            )

        return [
            TranscriptEvent(
                event_id=f"event-transcript-err-{session_id}-{self._call_count}",
                event_type="transcript.error",
                schema_version="1.0",
                session_id=session_id,
                correlation_id=correlation_id,
                timestamp=timestamp,
                producer="transcription",
                payload=payload,
            )
        ]
