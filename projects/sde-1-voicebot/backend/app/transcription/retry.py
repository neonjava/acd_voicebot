"""Bounded retry policy and error normalization for transcription adapter."""

from collections.abc import Callable, Sequence
from datetime import datetime

from app.contracts.common import ErrorEnvelope
from app.contracts.transcription import TranscriptEvent, TranscriptSegment


class RetryPolicy:
    """Bounded retry policy for retryable transcription failures.

    - Retries only when error is marked retryable or has a recognized retryable code.
    - Non-retryable errors return immediately without retry.
    - If retries are exhausted, emits a normalized TRANSCRIPTION_RETRY_EXHAUSTED error.
    - Output that is not a list of TranscriptEvent values is not retried and becomes
      a safe TRANSCRIPTION_MALFORMED_OUTPUT error.
    - Enforces max_retries >= 0.
    """

    DEFAULT_RETRYABLE_CODES = frozenset(
        {
            "TRANSCRIPTION_TEMPORARY_ERROR",
            "TRANSCRIPTION_TIMEOUT",
            "PROVIDER_BUSY",
            "SERVICE_UNAVAILABLE",
        }
    )

    def __init__(
        self,
        *,
        max_retries: int = 2,
        retryable_codes: Sequence[str] | None = None,
    ) -> None:
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("max_retries must be a nonnegative integer")

        self.max_retries = max_retries
        self.retryable_codes = (
            frozenset(retryable_codes)
            if retryable_codes is not None
            else self.DEFAULT_RETRYABLE_CODES
        )
        self._call_count = 0

    def is_retryable(self, error: ErrorEnvelope) -> bool:
        """Determine if an ErrorEnvelope represents a transient, retryable failure."""
        if not isinstance(error, ErrorEnvelope):
            return False
        return error.retryable is True or error.code in self.retryable_codes

    def execute_with_retry(
        self,
        action: Callable[[], list[TranscriptEvent]],
        *,
        session_id: str,
        correlation_id: str,
        timestamp: datetime,
        batch_id: int | str | None = None,
    ) -> tuple[list[TranscriptEvent], int]:
        """Execute an action with bounded retries.

        Returns (events, attempts_count).
        """
        self._call_count += 1
        batch_key = str(batch_id) if batch_id is not None else str(self._call_count)
        attempts = 0
        max_attempts = self.max_retries + 1
        last_error_event: TranscriptEvent | None = None
        accumulated_success_events: dict[str, TranscriptEvent] = {}

        while attempts < max_attempts:
            attempts += 1
            try:
                events = action()
            except TimeoutError:
                err_envelope = ErrorEnvelope(
                    code="TRANSCRIPTION_TIMEOUT",
                    message_safe_for_user="Transcription request timed out.",
                    retryable=True,
                    correlation_id=correlation_id,
                    details_redacted={"attempt": str(attempts)},
                )
                last_error_event = TranscriptEvent(
                    event_id=(
                        f"event-transcript-err-{session_id}-{batch_key}-{attempts}"
                    ),
                    event_type="transcript.error",
                    schema_version="1.0",
                    session_id=session_id,
                    correlation_id=correlation_id,
                    timestamp=timestamp,
                    producer="transcription",
                    payload=err_envelope,
                )
                # Check if we can retry
                if attempts < max_attempts:
                    continue
                break
            except Exception as exc:  # noqa: BLE001
                err_envelope = ErrorEnvelope(
                    code="TRANSCRIPTION_INTERNAL_ERROR",
                    message_safe_for_user=(
                        "An unexpected error occurred during transcription."
                    ),
                    retryable=False,
                    correlation_id=correlation_id,
                    details_redacted={
                        "attempt": str(attempts),
                        "exception_type": type(exc).__name__,
                    },
                )
                err_event = TranscriptEvent(
                    event_id=(
                        f"event-transcript-err-{session_id}-{batch_key}-{attempts}"
                    ),
                    event_type="transcript.error",
                    schema_version="1.0",
                    session_id=session_id,
                    correlation_id=correlation_id,
                    timestamp=timestamp,
                    producer="transcription",
                    payload=err_envelope,
                )
                return [*accumulated_success_events.values(), err_event], attempts

            if not isinstance(events, list) or not all(
                isinstance(evt, TranscriptEvent) for evt in events
            ):
                err_envelope = ErrorEnvelope(
                    code="TRANSCRIPTION_MALFORMED_OUTPUT",
                    message_safe_for_user=(
                        "The transcription provider returned an invalid response."
                    ),
                    retryable=False,
                    correlation_id=correlation_id,
                    details_redacted={"attempt": str(attempts)},
                )
                err_event = TranscriptEvent(
                    event_id=(
                        f"event-transcript-err-{session_id}-{batch_key}-{attempts}"
                    ),
                    event_type="transcript.error",
                    schema_version="1.0",
                    session_id=session_id,
                    correlation_id=correlation_id,
                    timestamp=timestamp,
                    producer="transcription",
                    payload=err_envelope,
                )
                return [*accumulated_success_events.values(), err_event], attempts

            # Accumulate successful segments across attempts by stable segment/event ID
            for evt in events:
                if evt.event_type != "transcript.error":
                    key = (
                        evt.payload.segment_id
                        if isinstance(evt.payload, TranscriptSegment)
                        else evt.event_id
                    )
                    if key in accumulated_success_events:
                        existing = accumulated_success_events[key]
                        if isinstance(
                            existing.payload, TranscriptSegment
                        ) and isinstance(evt.payload, TranscriptSegment):
                            if existing.payload.is_final and not evt.payload.is_final:
                                # Keep existing final segment when later result
                                # is interim regardless of sequence_id
                                pass
                            elif (
                                evt.payload.is_final and not existing.payload.is_final
                            ) or (
                                evt.payload.sequence_id >= existing.payload.sequence_id
                            ):
                                accumulated_success_events[key] = evt
                        else:
                            accumulated_success_events[key] = evt
                    else:
                        accumulated_success_events[key] = evt

            # Inspect all error events before retrying.
            error_events = [
                evt
                for evt in events
                if evt.event_type == "transcript.error"
                and isinstance(evt.payload, ErrorEnvelope)
            ]
            if not error_events:
                # Success: no errors in batch
                return [*accumulated_success_events.values()], attempts

            # A permanent error anywhere in the batch stops retries immediately
            for err_evt in error_events:
                if not self.is_retryable(err_evt.payload):
                    return [
                        *accumulated_success_events.values(),
                        *error_events,
                    ], attempts

            # All errors in the batch are retryable; record last error event
            last_error_event = error_events[-1]

        # If exhausted all attempts with retryable errors
        exhausted_envelope = ErrorEnvelope(
            code="TRANSCRIPTION_RETRY_EXHAUSTED",
            message_safe_for_user=(f"Transcription failed after {attempts} attempts."),
            retryable=False,
            correlation_id=correlation_id,
            details_redacted={
                "attempts": str(attempts),
                "last_error_code": (
                    last_error_event.payload.code
                    if last_error_event
                    and isinstance(last_error_event.payload, ErrorEnvelope)
                    else "UNKNOWN"
                ),
            },
        )
        exhausted_event = TranscriptEvent(
            event_id=f"event-transcript-err-{session_id}-{batch_key}-exhausted",
            event_type="transcript.error",
            schema_version="1.0",
            session_id=session_id,
            correlation_id=correlation_id,
            timestamp=timestamp,
            producer="transcription",
            payload=exhausted_envelope,
        )
        # Preserve successful segments accumulated across all attempts
        return [*accumulated_success_events.values(), exhausted_event], attempts
