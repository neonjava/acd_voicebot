"""Tests for TranscriptionOrchestrator: audio pipeline, retries, and handoffs."""

from datetime import datetime, timezone

import pytest

from app.audio.chunker import chunk_pcm
from app.audio.source import make_fake_pcm
from app.contracts.common import ErrorEnvelope
from app.contracts.reasoning import ReasoningRequest
from app.contracts.transcription import TranscriptEvent, TranscriptSegment
from app.reasoning.context import context_item_from_transcript
from app.reasoning.mock import reason
from app.transcription.accumulator import SegmentAccumulator
from app.transcription.mock import FakeTranscriber
from app.transcription.orchestrator import TranscriptionOrchestrator
from app.transcription.preprocessing import AudioPreprocessor
from app.transcription.retry import RetryPolicy


@pytest.fixture
def sample_chunks():
    pcm = make_fake_pcm(duration_ms=200)
    return chunk_pcm(pcm, session_id="session-orch", chunk_ms=20)


@pytest.fixture
def fixed_timestamp():
    return datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class TestTranscriptionOrchestrator:
    def test_end_to_end_pipeline_success(self, sample_chunks, fixed_timestamp) -> None:
        orchestrator = TranscriptionOrchestrator()
        assert orchestrator.health() == "ready"

        events = orchestrator.process_chunks(
            sample_chunks,
            session_id="session-orch",
            correlation_id="corr-orch",
            timestamp=fixed_timestamp,
        )

        assert len(events) == 1
        assert events[0].event_type == "transcript.segment"
        segment = events[0].payload
        assert isinstance(segment, TranscriptSegment)
        assert segment.text == "Hello from the mock voicebot."
        assert segment.start_ms == 0
        assert segment.end_ms == 200
        assert segment.is_final is True

        # Check accumulator integration
        assert orchestrator.get_transcript_text() == "Hello from the mock voicebot."
        assert len(orchestrator.get_segments()) == 1
        assert len(orchestrator.get_final_segments()) == 1

    def test_orchestrator_handles_empty_chunks(self, fixed_timestamp) -> None:
        orchestrator = TranscriptionOrchestrator()
        events = orchestrator.process_chunks(
            [],
            session_id="session-orch",
            correlation_id="corr-orch",
            timestamp=fixed_timestamp,
        )
        assert events == []
        assert orchestrator.get_segments() == []

    def test_orchestrator_recovers_from_transient_failure_via_retry(
        self, sample_chunks, fixed_timestamp
    ) -> None:
        # Fails once with transient error, then succeeds
        fake = FakeTranscriber(
            failures_before_success=1, failure_mode="temporary_error"
        )
        orchestrator = TranscriptionOrchestrator(
            adapter=fake,
            retry_policy=RetryPolicy(max_retries=2),
        )

        events = orchestrator.process_chunks(
            sample_chunks,
            session_id="session-orch",
            correlation_id="corr-orch",
            timestamp=fixed_timestamp,
        )

        assert len(events) == 1
        assert events[0].event_type == "transcript.segment"
        assert events[0].payload.text == "Hello from the mock voicebot."
        assert orchestrator.get_transcript_text() == "Hello from the mock voicebot."

    def test_orchestrator_emits_error_when_retries_exhausted(
        self, sample_chunks, fixed_timestamp
    ) -> None:
        # Fails persistently
        fake = FakeTranscriber(failure_mode="temporary_error")
        orchestrator = TranscriptionOrchestrator(
            adapter=fake,
            retry_policy=RetryPolicy(max_retries=1),
        )

        events = orchestrator.process_chunks(
            sample_chunks,
            session_id="session-orch",
            correlation_id="corr-orch",
            timestamp=fixed_timestamp,
        )

        assert len(events) == 1
        assert events[0].event_type == "transcript.error"
        err = events[0].payload
        assert isinstance(err, ErrorEnvelope)
        assert err.code == "TRANSCRIPTION_RETRY_EXHAUSTED"
        assert err.retryable is False
        # Error events should not be added to accumulator
        assert orchestrator.get_segments() == []

    def test_orchestrator_non_retryable_failure_emitted_immediately(
        self, sample_chunks, fixed_timestamp
    ) -> None:
        fake = FakeTranscriber(failure_mode="permanent_error")
        orchestrator = TranscriptionOrchestrator(
            adapter=fake,
            retry_policy=RetryPolicy(max_retries=2),
        )

        events = orchestrator.process_chunks(
            sample_chunks,
            session_id="session-orch",
            correlation_id="corr-orch",
            timestamp=fixed_timestamp,
        )

        assert len(events) == 1
        assert events[0].event_type == "transcript.error"
        err = events[0].payload
        assert isinstance(err, ErrorEnvelope)
        assert err.code == "TRANSCRIPTION_PERMANENT_ERROR"
        assert err.retryable is False

    def test_orchestrator_timeout_handling(
        self, sample_chunks, fixed_timestamp
    ) -> None:
        fake = FakeTranscriber(failure_mode="timeout")
        orchestrator = TranscriptionOrchestrator(
            adapter=fake,
            retry_policy=RetryPolicy(max_retries=1),
        )

        events = orchestrator.process_chunks(
            sample_chunks,
            session_id="session-orch",
            correlation_id="corr-orch",
            timestamp=fixed_timestamp,
        )

        assert len(events) == 1
        assert events[0].event_type == "transcript.error"
        err = events[0].payload
        assert isinstance(err, ErrorEnvelope)
        assert err.code == "TRANSCRIPTION_RETRY_EXHAUSTED"

    def test_orchestrator_cancellation(self, sample_chunks, fixed_timestamp) -> None:
        orchestrator = TranscriptionOrchestrator()
        orchestrator.cancel("session-orch")

        events = orchestrator.process_chunks(
            sample_chunks,
            session_id="session-orch",
            correlation_id="corr-orch",
            timestamp=fixed_timestamp,
        )
        assert events == []
        assert orchestrator.get_segments() == []

    @pytest.mark.parametrize("invalid_id", ["", "   ", None])
    def test_orchestrator_rejects_invalid_identifiers(
        self, sample_chunks, fixed_timestamp, invalid_id
    ) -> None:
        orchestrator = TranscriptionOrchestrator()
        with pytest.raises(ValueError, match="nonempty string"):
            orchestrator.process_chunks(
                sample_chunks,
                session_id=invalid_id,  # type: ignore
                correlation_id="corr-orch",
                timestamp=fixed_timestamp,
            )
        with pytest.raises(ValueError, match="nonempty string"):
            orchestrator.process_chunks(
                sample_chunks,
                session_id="session-orch",
                correlation_id=invalid_id,  # type: ignore
                timestamp=fixed_timestamp,
            )

    def test_orchestrator_w1_w2_w3_connected_handoff(self, fixed_timestamp) -> None:
        """Verify real W1 chunks flow to W2 and produce valid W3 context items."""
        # 1. W1 chunk generation
        pcm = make_fake_pcm(duration_ms=1000)
        chunks = chunk_pcm(pcm, session_id="session-connected", chunk_ms=20)
        assert len(chunks) == 50

        # 2. W2 orchestration with preprocessing and retry policy
        orchestrator = TranscriptionOrchestrator(
            adapter=FakeTranscriber(),
            preprocessor=AudioPreprocessor(normalize=True),
            retry_policy=RetryPolicy(max_retries=2),
            accumulator=SegmentAccumulator(),
        )
        events = orchestrator.process_chunks(
            chunks,
            session_id="session-connected",
            correlation_id="corr-connected",
            timestamp=fixed_timestamp,
        )
        assert len(events) == 1
        assert orchestrator.get_transcript_text() == "Hello from the mock voicebot."

        # 3. W3 reasoning handoff
        finals = orchestrator.get_final_segments()
        assert len(finals) == 1
        context_item = context_item_from_transcript(finals[0])
        assert context_item.source.kind == "transcript"
        assert context_item.source.source_id == finals[0].segment_id
        assert context_item.text == finals[0].text

        # Verify W3 reasoner can answer using this context
        req = ReasoningRequest(
            request_id="req-orch-1",
            session_id="session-connected",
            question="What is the voicebot greeting?",
            context=[context_item],
        )
        res = reason(req)
        assert res.insufficient_evidence is False
        assert res.source_ids == [finals[0].segment_id]
        assert res.answer != ""

    def test_orchestrator_direct_event_ingestion_and_reset(
        self, fixed_timestamp
    ) -> None:
        orchestrator = TranscriptionOrchestrator()
        seg = TranscriptSegment(
            segment_id="seg-ext",
            session_id="sess-ext",
            sequence_id=0,
            start_ms=0,
            end_ms=500,
            text="External",
            is_final=True,
        )
        evt = orchestrator.ingest_event(
            TranscriptEvent(
                event_id="evt-ext",
                event_type="transcript.segment",
                schema_version="1.0",
                session_id="sess-ext",
                correlation_id="corr-ext",
                timestamp=fixed_timestamp,
                producer="transcription",
                payload=seg,
            )
        )
        assert evt is True
        assert orchestrator.get_transcript_text() == "External"
        assert orchestrator.get_revisions("seg-ext") == 0
        assert orchestrator.get_gaps() == []

        orchestrator.reset()
        assert orchestrator.get_segments() == []
        assert orchestrator.get_transcript_text() == ""

    def test_orchestrator_preserves_segments_when_mixed_batch_fails_retries(
        self, sample_chunks, fixed_timestamp
    ) -> None:
        """Segments in mixed batch are added to accumulator despite error."""

        class MixedBatchAdapter:
            def transcribe(
                self, chunks, *, session_id, correlation_id, timestamp
            ) -> list[TranscriptEvent]:
                seg = TranscriptSegment(
                    segment_id="seg-mixed",
                    session_id=session_id,
                    sequence_id=0,
                    start_ms=0,
                    end_ms=200,
                    text="Mixed segment",
                    is_final=True,
                )
                seg_evt = TranscriptEvent(
                    event_id="evt-seg-mixed",
                    event_type="transcript.segment",
                    schema_version="1.0",
                    session_id=session_id,
                    correlation_id=correlation_id,
                    timestamp=timestamp,
                    producer="transcription",
                    payload=seg,
                )
                err_evt = TranscriptEvent(
                    event_id="evt-err-mixed",
                    event_type="transcript.error",
                    schema_version="1.0",
                    session_id=session_id,
                    correlation_id=correlation_id,
                    timestamp=timestamp,
                    producer="transcription",
                    payload=ErrorEnvelope(
                        code="TRANSCRIPTION_TEMPORARY_ERROR",
                        message_safe_for_user="Transient glitch",
                        retryable=True,
                        correlation_id=correlation_id,
                    ),
                )
                return [seg_evt, err_evt]

        orchestrator = TranscriptionOrchestrator(
            adapter=MixedBatchAdapter(),
            retry_policy=RetryPolicy(max_retries=0),
        )
        events = orchestrator.process_chunks(
            sample_chunks,
            session_id="session-orch",
            correlation_id="corr-orch",
            timestamp=fixed_timestamp,
        )

        assert len(events) == 2
        assert events[0].event_type == "transcript.segment"
        assert events[1].event_type == "transcript.error"
        assert orchestrator.get_transcript_text() == "Mixed segment"
        assert len(orchestrator.get_segments()) == 1
