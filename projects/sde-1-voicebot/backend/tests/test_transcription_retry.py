"""Tests for bounded retry policy and error normalization in transcription."""

from datetime import datetime, timezone

import pytest

from app.contracts.common import ErrorEnvelope
from app.contracts.transcription import TranscriptEvent, TranscriptSegment
from app.transcription.retry import RetryPolicy


def _make_success_event(session_id: str = "sess-retry") -> TranscriptEvent:
    return TranscriptEvent(
        event_id=f"evt-{session_id}",
        event_type="transcript.segment",
        schema_version="1.0",
        session_id=session_id,
        correlation_id="corr-test",
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        producer="transcription",
        payload=TranscriptSegment(
            segment_id="seg-1",
            session_id=session_id,
            sequence_id=0,
            start_ms=0,
            end_ms=1000,
            text="Success",
            is_final=True,
        ),
    )


def _make_error_event(
    code: str, retryable: bool, session_id: str = "sess-retry"
) -> TranscriptEvent:
    return TranscriptEvent(
        event_id=f"evt-err-{session_id}",
        event_type="transcript.error",
        schema_version="1.0",
        session_id=session_id,
        correlation_id="corr-test",
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        producer="transcription",
        payload=ErrorEnvelope(
            code=code,
            message_safe_for_user="Simulated error",
            retryable=retryable,
            correlation_id="corr-test",
        ),
    )


class TestRetryPolicy:
    def test_success_on_first_try(self) -> None:
        policy = RetryPolicy(max_retries=2)
        call_count = 0

        def action() -> list[TranscriptEvent]:
            nonlocal call_count
            call_count += 1
            return [_make_success_event()]

        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events, attempts = policy.execute_with_retry(
            action, session_id="sess", correlation_id="corr", timestamp=ts
        )
        assert attempts == 1
        assert call_count == 1
        assert len(events) == 1
        assert events[0].event_type == "transcript.segment"

    def test_retries_transient_failure_and_recovers(self) -> None:
        policy = RetryPolicy(max_retries=2)
        call_count = 0

        def action() -> list[TranscriptEvent]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    _make_error_event("TRANSCRIPTION_TEMPORARY_ERROR", retryable=True)
                ]
            return [_make_success_event()]

        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events, attempts = policy.execute_with_retry(
            action, session_id="sess", correlation_id="corr", timestamp=ts
        )
        assert attempts == 2
        assert call_count == 2
        assert len(events) == 1
        assert events[0].event_type == "transcript.segment"

    def test_exhausts_retries_on_persistent_transient_failure(self) -> None:
        policy = RetryPolicy(max_retries=2)  # 1 initial + 2 retries = 3 attempts
        call_count = 0

        def action() -> list[TranscriptEvent]:
            nonlocal call_count
            call_count += 1
            return [_make_error_event("TRANSCRIPTION_TEMPORARY_ERROR", retryable=True)]

        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events, attempts = policy.execute_with_retry(
            action, session_id="sess", correlation_id="corr", timestamp=ts
        )
        assert attempts == 3
        assert call_count == 3
        assert len(events) == 1
        assert events[0].event_type == "transcript.error"
        err = events[0].payload
        assert isinstance(err, ErrorEnvelope)
        assert err.code == "TRANSCRIPTION_RETRY_EXHAUSTED"
        assert err.retryable is False
        assert "3 attempts" in err.message_safe_for_user

    def test_non_retryable_error_fails_immediately_without_retry(self) -> None:
        policy = RetryPolicy(max_retries=3)
        call_count = 0

        def action() -> list[TranscriptEvent]:
            nonlocal call_count
            call_count += 1
            return [_make_error_event("TRANSCRIPTION_INVALID_PAYLOAD", retryable=False)]

        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events, attempts = policy.execute_with_retry(
            action, session_id="sess", correlation_id="corr", timestamp=ts
        )
        assert attempts == 1
        assert call_count == 1
        assert len(events) == 1
        err = events[0].payload
        assert isinstance(err, ErrorEnvelope)
        assert err.code == "TRANSCRIPTION_INVALID_PAYLOAD"

    def test_retry_policy_batch_with_temporary_then_permanent_fails_immediately(
        self,
    ) -> None:
        """Batch with temporary then permanent error must fail immediately."""
        policy = RetryPolicy(max_retries=3)
        call_count = 0

        def action() -> list[TranscriptEvent]:
            nonlocal call_count
            call_count += 1
            return [
                _make_error_event("TRANSCRIPTION_TEMPORARY_ERROR", retryable=True),
                _make_error_event("TRANSCRIPTION_INVALID_PAYLOAD", retryable=False),
            ]

        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events, attempts = policy.execute_with_retry(
            action, session_id="sess", correlation_id="corr", timestamp=ts
        )
        assert attempts == 1
        assert call_count == 1
        assert len(events) == 2
        assert any(
            isinstance(e.payload, ErrorEnvelope) and e.payload.retryable is False
            for e in events
        )

    def test_retry_policy_batch_with_permanent_then_temporary_fails_immediately(
        self,
    ) -> None:
        """Batch with permanent then temporary error must fail immediately."""
        policy = RetryPolicy(max_retries=3)
        call_count = 0

        def action() -> list[TranscriptEvent]:
            nonlocal call_count
            call_count += 1
            return [
                _make_error_event("TRANSCRIPTION_INVALID_PAYLOAD", retryable=False),
                _make_error_event("TRANSCRIPTION_TEMPORARY_ERROR", retryable=True),
            ]

        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events, attempts = policy.execute_with_retry(
            action, session_id="sess", correlation_id="corr", timestamp=ts
        )
        assert attempts == 1
        assert call_count == 1
        assert len(events) == 2
        assert any(
            isinstance(e.payload, ErrorEnvelope) and e.payload.retryable is False
            for e in events
        )

    def test_retry_policy_preserves_successful_segments_when_exhausted(self) -> None:
        """Exhausting retries preserves valid segments from final mixed batch."""
        policy = RetryPolicy(max_retries=1)
        call_count = 0

        def action() -> list[TranscriptEvent]:
            nonlocal call_count
            call_count += 1
            return [
                _make_success_event(),
                _make_error_event("TRANSCRIPTION_TEMPORARY_ERROR", retryable=True),
            ]

        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events, attempts = policy.execute_with_retry(
            action, session_id="sess", correlation_id="corr", timestamp=ts
        )
        assert attempts == 2
        assert call_count == 2
        assert len(events) == 2
        assert events[0].event_type == "transcript.segment"
        assert events[1].event_type == "transcript.error"
        err = events[1].payload
        assert isinstance(err, ErrorEnvelope)
        assert err.code == "TRANSCRIPTION_RETRY_EXHAUSTED"

    def test_retry_policy_mixed_batch_with_zero_retries_preserves_segments(
        self,
    ) -> None:
        """With max_retries=0, valid segments in mixed batch are preserved."""
        policy = RetryPolicy(max_retries=0)
        call_count = 0

        def action() -> list[TranscriptEvent]:
            nonlocal call_count
            call_count += 1
            return [
                _make_success_event(),
                _make_error_event("TRANSCRIPTION_TEMPORARY_ERROR", retryable=True),
            ]

        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events, attempts = policy.execute_with_retry(
            action, session_id="sess", correlation_id="corr", timestamp=ts
        )
        assert attempts == 1
        assert call_count == 1
        assert len(events) == 2
        assert events[0].event_type == "transcript.segment"
        assert events[1].event_type == "transcript.error"
        err = events[1].payload
        assert isinstance(err, ErrorEnvelope)
        assert err.code == "TRANSCRIPTION_RETRY_EXHAUSTED"

    def test_retry_policy_accumulates_segments_when_retry_times_out(self) -> None:
        """Attempt 1 returns valid segment + retryable error; attempt 2 times out.

        Valid segment from attempt 1 must be preserved when retries are exhausted.
        """
        policy = RetryPolicy(max_retries=1)
        call_count = 0

        def action() -> list[TranscriptEvent]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    _make_success_event(),
                    _make_error_event("TRANSCRIPTION_TEMPORARY_ERROR", retryable=True),
                ]
            raise TimeoutError("connection dropped on retry")

        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events, attempts = policy.execute_with_retry(
            action, session_id="sess", correlation_id="corr", timestamp=ts
        )
        assert attempts == 2
        assert call_count == 2
        assert len(events) == 2
        assert events[0].event_type == "transcript.segment"
        assert events[0].payload.text == "Success"
        assert events[1].event_type == "transcript.error"
        err = events[1].payload
        assert isinstance(err, ErrorEnvelope)
        assert err.code == "TRANSCRIPTION_RETRY_EXHAUSTED"

    def test_retry_policy_deduplicates_segments_by_segment_id(self) -> None:
        """Updated versions of segments with same segment_id are deduplicated."""
        policy = RetryPolicy(max_retries=1)
        call_count = 0

        def action() -> list[TranscriptEvent]:
            nonlocal call_count
            call_count += 1
            is_final = call_count == 2
            seg = TranscriptSegment(
                segment_id="seg-dedup",
                session_id="sess",
                sequence_id=call_count,
                start_ms=0,
                end_ms=1000,
                text=f"Draft v{call_count}",
                is_final=is_final,
            )
            evt = TranscriptEvent(
                event_id=f"evt-{call_count}",
                event_type="transcript.segment",
                schema_version="1.0",
                session_id="sess",
                correlation_id="corr",
                timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                producer="transcription",
                payload=seg,
            )
            return [
                evt,
                _make_error_event("TRANSCRIPTION_TEMPORARY_ERROR", retryable=True),
            ]

        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events, attempts = policy.execute_with_retry(
            action, session_id="sess", correlation_id="corr", timestamp=ts
        )
        assert attempts == 2
        assert len(events) == 2
        assert events[0].event_type == "transcript.segment"
        assert events[0].payload.segment_id == "seg-dedup"
        assert events[0].payload.text == "Draft v2"
        assert events[0].payload.is_final is True
        assert events[1].event_type == "transcript.error"

    def test_retry_policy_preserves_final_segment_over_subsequent_interim(self) -> None:
        """Attempt 1 returns final segment + retryable error; attempt 2 returns interim.

        An interim segment on retry with higher sequence_id must not
        overwrite an existing final segment.
        """
        policy = RetryPolicy(max_retries=1)
        call_count = 0

        def action() -> list[TranscriptEvent]:
            nonlocal call_count
            call_count += 1
            is_final = call_count == 1
            seg = TranscriptSegment(
                segment_id="seg-final-preserved",
                session_id="sess",
                sequence_id=call_count,
                start_ms=0,
                end_ms=1000,
                text=f"Version {call_count}",
                is_final=is_final,
            )
            evt = TranscriptEvent(
                event_id=f"evt-{call_count}",
                event_type="transcript.segment",
                schema_version="1.0",
                session_id="sess",
                correlation_id="corr",
                timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                producer="transcription",
                payload=seg,
            )
            if call_count == 1:
                return [
                    evt,
                    _make_error_event("TRANSCRIPTION_TEMPORARY_ERROR", retryable=True),
                ]
            return [evt]

        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events, attempts = policy.execute_with_retry(
            action, session_id="sess", correlation_id="corr", timestamp=ts
        )
        assert attempts == 2
        assert len(events) == 1
        assert events[0].event_type == "transcript.segment"
        assert events[0].payload.segment_id == "seg-final-preserved"
        assert events[0].payload.text == "Version 1"
        assert events[0].payload.is_final is True

    def test_timeout_exception_handled_and_retried(self) -> None:
        policy = RetryPolicy(max_retries=1)
        call_count = 0

        def action() -> list[TranscriptEvent]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("timeout")
            return [_make_success_event()]

        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events, attempts = policy.execute_with_retry(
            action, session_id="sess", correlation_id="corr", timestamp=ts
        )
        assert attempts == 2
        assert len(events) == 1
        assert events[0].event_type == "transcript.segment"

    def test_unexpected_exception_normalized_without_crashing(self) -> None:
        policy = RetryPolicy(max_retries=2)

        def action() -> list[TranscriptEvent]:
            raise RuntimeError("unexpected internal driver error")

        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events, attempts = policy.execute_with_retry(
            action, session_id="sess", correlation_id="corr", timestamp=ts
        )
        assert attempts == 1
        assert len(events) == 1
        assert events[0].event_type == "transcript.error"
        err = events[0].payload
        assert isinstance(err, ErrorEnvelope)
        assert err.code == "TRANSCRIPTION_INTERNAL_ERROR"
        assert err.retryable is False

    def test_retry_policy_emits_unique_error_event_ids_across_calls(self) -> None:
        """Successive failing calls to execute_with_retry emit distinct event_ids."""
        policy = RetryPolicy(max_retries=1)

        def action() -> list[TranscriptEvent]:
            return [_make_error_event("TRANSCRIPTION_TEMPORARY_ERROR", retryable=True)]

        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events1, _ = policy.execute_with_retry(
            action, session_id="s1", correlation_id="c1", timestamp=ts
        )
        events2, _ = policy.execute_with_retry(
            action, session_id="s1", correlation_id="c2", timestamp=ts
        )

        assert events1[0].event_id != events2[0].event_id
        assert events1[0].event_id == "event-transcript-err-s1-1-exhausted"
        assert events2[0].event_id == "event-transcript-err-s1-2-exhausted"

    def test_invalid_max_retries_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="nonnegative integer"):
            RetryPolicy(max_retries=-1)
        with pytest.raises(ValueError, match="nonnegative integer"):
            RetryPolicy(max_retries="two")  # type: ignore
