"""Bounded retry policy and error normalization for transcription adapter."""

from collections.abc import Callable, Sequence
from datetime import datetime

from app.contracts.common import ErrorEnvelope
from app.contracts.transcription import TranscriptEvent


class RetryPolicy:
    """Bounded retry policy for retryable transcription failures.

    - Retries only when error is marked retryable or has a recognized retryable code.
    - Non-retryable errors return immediately without retry.
    - If retries are exhausted, emits a normalized TRANSCRIPTION_RETRY_EXHAUSTED error.
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
    ) -> tuple[list[TranscriptEvent], int]:
        """Execute an action with bounded retries.

        Returns (events, attempts_count).
        """
        attempts = 0
        max_attempts = self.max_retries + 1
        last_error_event: TranscriptEvent | None = None

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
                    event_id=f"event-transcript-err-{session_id}-{attempts}",
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
                return (
                    [
                        TranscriptEvent(
                            event_id=f"event-transcript-err-{session_id}-{attempts}",
                            event_type="transcript.error",
                            schema_version="1.0",
                            session_id=session_id,
                            correlation_id=correlation_id,
                            timestamp=timestamp,
                            producer="transcription",
                            payload=err_envelope,
                        )
                    ],
                    attempts,
                )

            # Check if returned events contain an error payload
            has_error = False
            for evt in events:
                if evt.event_type == "transcript.error" and isinstance(
                    evt.payload, ErrorEnvelope
                ):
                    has_error = True
                    last_error_event = evt
                    if not self.is_retryable(evt.payload):
                        # Non-retryable error fails immediately
                        return events, attempts
                    break

            if not has_error:
                # Success
                return events, attempts

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
        return (
            [
                TranscriptEvent(
                    event_id=f"event-transcript-err-{session_id}-exhausted",
                    event_type="transcript.error",
                    schema_version="1.0",
                    session_id=session_id,
                    correlation_id=correlation_id,
                    timestamp=timestamp,
                    producer="transcription",
                    payload=exhausted_envelope,
                )
            ],
            attempts,
        )
