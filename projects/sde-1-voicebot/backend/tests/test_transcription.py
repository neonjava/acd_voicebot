"""Tests for transcription adapter, fake transcriber, and segment accumulator."""

from datetime import datetime, timezone

import pytest

try:
    from app.contracts.audio import AudioChunk, AudioFormat
except ImportError:
    from typing import Literal, Self

    from pydantic import Field, model_validator

    from app.contracts.common import ContractModel

    class AudioFormat(ContractModel):
        sample_rate_hz: Literal[16000] = 16000
        channels: Literal[1] = 1
        encoding: Literal["pcm_s16le"] = "pcm_s16le"

    class AudioChunk(ContractModel):
        session_id: str = Field(min_length=1, pattern=r"\S")
        sequence_id: int = Field(strict=True, ge=0)
        start_ms: int = Field(strict=True, ge=0)
        duration_ms: int = Field(strict=True, gt=0)
        format: AudioFormat
        pcm: bytes = Field(strict=True, min_length=1, repr=False)

        @model_validator(mode="after")
        def require_matching_pcm_length(self) -> Self:
            expected = self.duration_ms * 32
            if len(self.pcm) != expected:
                raise ValueError(
                    f"expected {expected} PCM bytes, received {len(self.pcm)}"
                )
            return self


from app.contracts.common import ErrorEnvelope
from app.contracts.transcription import TranscriptEvent, TranscriptSegment
from app.transcription.accumulator import SegmentAccumulator
from app.transcription.adapter import TranscriptionAdapter
from app.transcription.mock import FakeTranscriber


def _make_audio_chunks(
    session_id: str = "session-test",
    count: int = 5,
    chunk_ms: int = 20,
    start_offset: int = 0,
) -> list[AudioChunk]:
    chunks: list[AudioChunk] = []
    for seq in range(count):
        start_ms = start_offset + seq * chunk_ms
        pcm = bytes(chunk_ms * 32)
        chunks.append(
            AudioChunk(
                session_id=session_id,
                sequence_id=seq,
                start_ms=start_ms,
                duration_ms=chunk_ms,
                format=AudioFormat(),
                pcm=pcm,
            )
        )
    return chunks


class TestFakeTranscriber:
    """Test suite for FakeTranscriber and TranscriptionAdapter protocol."""

    def test_implements_protocol(self):
        transcriber = FakeTranscriber()
        assert isinstance(transcriber, TranscriptionAdapter)

    def test_health_returns_ready(self):
        transcriber = FakeTranscriber()
        assert transcriber.health() == "ready"

    @pytest.mark.parametrize("timeout", [0, -1, -5.0, "5"])
    def test_invalid_timeout_raises(self, timeout: object):
        with pytest.raises(
            ValueError, match="timeout_seconds must be a positive number"
        ):
            FakeTranscriber(timeout_seconds=timeout)  # type: ignore

    def test_empty_chunks_returns_empty_list(self):
        transcriber = FakeTranscriber()
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = transcriber.transcribe(
            [],
            session_id="session-test",
            correlation_id="corr-test",
            timestamp=ts,
        )
        assert result == []

    def test_valid_chunks_produce_final_segment(self):
        transcriber = FakeTranscriber()
        chunks = _make_audio_chunks("session-demo", count=50, chunk_ms=20)
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        events = transcriber.transcribe(
            chunks,
            session_id="session-demo",
            correlation_id="corr-demo",
            timestamp=ts,
        )
        assert len(events) == 1
        event = events[0]
        assert event.event_type == "transcript.segment"
        assert event.session_id == "session-demo"
        assert event.correlation_id == "corr-demo"
        assert event.producer == "transcription"
        assert event.timestamp == ts

        seg = event.payload
        assert isinstance(seg, TranscriptSegment)
        assert seg.segment_id == "session-demo-segment-0"
        assert seg.session_id == "session-demo"
        assert seg.sequence_id == 0
        assert seg.start_ms == 0
        assert seg.end_ms == 1000
        assert seg.text == "Hello from the mock voicebot."
        assert seg.confidence == 1.0
        assert seg.language == "en"
        assert seg.is_final is True

    def test_subsequent_calls_increment_segment_index(self):
        transcriber = FakeTranscriber()
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        chunks1 = _make_audio_chunks(
            "session-inc", count=5, chunk_ms=20, start_offset=0
        )
        chunks2 = _make_audio_chunks(
            "session-inc", count=5, chunk_ms=20, start_offset=100
        )

        events1 = transcriber.transcribe(
            chunks1, session_id="session-inc", correlation_id="c1", timestamp=ts
        )
        events2 = transcriber.transcribe(
            chunks2, session_id="session-inc", correlation_id="c2", timestamp=ts
        )
        assert events1[0].payload.segment_id == "session-inc-segment-0"
        assert events2[0].payload.segment_id == "session-inc-segment-1"

    def test_cancellation_prevents_subsequent_output(self):
        transcriber = FakeTranscriber()
        chunks = _make_audio_chunks("session-cancel", count=5)
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        # Before cancel
        events = transcriber.transcribe(
            chunks, session_id="session-cancel", correlation_id="c1", timestamp=ts
        )
        assert len(events) == 1

        # Cancel
        transcriber.cancel("session-cancel")

        # After cancel: returns empty
        events_after = transcriber.transcribe(
            chunks, session_id="session-cancel", correlation_id="c2", timestamp=ts
        )
        assert events_after == []

        # Another session is unaffected
        chunks_other = _make_audio_chunks("session-active", count=5)
        events_other = transcriber.transcribe(
            chunks_other, session_id="session-active", correlation_id="c3", timestamp=ts
        )
        assert len(events_other) == 1

    def test_invalid_cancel_session_raises(self):
        transcriber = FakeTranscriber()
        with pytest.raises(ValueError, match="session_id must be a nonempty string"):
            transcriber.cancel("")

    def test_mixed_session_chunks_produce_transcript_error_event(self):
        transcriber = FakeTranscriber()
        chunks = _make_audio_chunks("session-A", count=3)
        # Malformed: third chunk has different session_id
        pcm = bytes(20 * 32)
        chunks[2] = AudioChunk(
            session_id="session-B",
            sequence_id=2,
            start_ms=40,
            duration_ms=20,
            format=AudioFormat(),
            pcm=pcm,
        )
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events = transcriber.transcribe(
            chunks, session_id="session-A", correlation_id="corr-err", timestamp=ts
        )
        assert len(events) == 1
        event = events[0]
        assert event.event_type == "transcript.error"
        assert isinstance(event.payload, ErrorEnvelope)
        assert event.payload.code == "TRANSCRIPTION_MIXED_SESSION"
        assert event.payload.correlation_id == "corr-err"
        assert event.payload.retryable is False

    def test_out_of_order_chunks_produce_transcript_error_event(self):
        transcriber = FakeTranscriber()
        chunks = _make_audio_chunks("session-order", count=3)
        # Swap chunks to make them out of order
        chunks[0], chunks[1] = chunks[1], chunks[0]

        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events = transcriber.transcribe(
            chunks, session_id="session-order", correlation_id="corr-err", timestamp=ts
        )
        assert len(events) == 1
        event = events[0]
        assert event.event_type == "transcript.error"
        assert isinstance(event.payload, ErrorEnvelope)
        assert event.payload.code == "TRANSCRIPTION_INVALID_ORDERING"

    @pytest.mark.parametrize(
        "sess,corr",
        [("", "corr"), ("   ", "corr"), ("sess", ""), ("sess", "   ")],
    )
    def test_empty_identifiers_raise_value_error(self, sess: str, corr: str):
        transcriber = FakeTranscriber()
        chunks = _make_audio_chunks("sess", count=1)
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            transcriber.transcribe(
                chunks, session_id=sess, correlation_id=corr, timestamp=ts
            )

    def test_naive_timestamp_raises_value_error(self):
        transcriber = FakeTranscriber()
        chunks = _make_audio_chunks("sess", count=1)
        naive_ts = datetime(2026, 1, 1, 0, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            transcriber.transcribe(
                chunks, session_id="sess", correlation_id="corr", timestamp=naive_ts
            )

    def test_real_w1_audio_to_w2_transcription_integration(self):
        """Verify real W1 make_fake_pcm and chunk_pcm feed into FakeTranscriber."""
        try:
            from app.audio.chunker import chunk_pcm
            from app.audio.source import make_fake_pcm
        except ImportError:
            pytest.skip("W1 audio source/chunker not present in branch")

        pcm = make_fake_pcm(duration_ms=1000)
        assert len(pcm) == 32000
        chunks = chunk_pcm(pcm, session_id="session-integration", chunk_ms=20)
        assert len(chunks) == 50

        transcriber = FakeTranscriber()
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events = transcriber.transcribe(
            chunks,
            session_id="session-integration",
            correlation_id="corr-integration",
            timestamp=ts,
        )
        assert len(events) == 1
        assert events[0].payload.text == "Hello from the mock voicebot."
        assert events[0].payload.start_ms == 0
        assert events[0].payload.end_ms == 1000

        acc = SegmentAccumulator()
        acc.add(events[0])
        assert acc.text() == "Hello from the mock voicebot."


class TestSegmentAccumulator:
    """Test suite for SegmentAccumulator."""

    def _make_event(
        self,
        segment_id: str,
        session_id: str = "sess-acc",
        sequence_id: int = 0,
        start_ms: int = 0,
        end_ms: int | None = None,
        text: str = "Test",
        confidence: float = 0.9,
        is_final: bool = True,
    ) -> TranscriptEvent:
        if end_ms is None:
            end_ms = start_ms + 1000
        seg = TranscriptSegment(
            segment_id=segment_id,
            session_id=session_id,
            sequence_id=sequence_id,
            start_ms=start_ms,
            end_ms=end_ms,
            text=text,
            confidence=confidence,
            language="en",
            is_final=is_final,
        )
        return TranscriptEvent(
            event_id=f"evt-{segment_id}",
            event_type="transcript.segment",
            schema_version="1.0",
            session_id=session_id,
            correlation_id="corr-acc",
            timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            producer="transcription",
            payload=seg,
        )

    def test_empty_accumulator(self):
        acc = SegmentAccumulator()
        assert acc.session_id is None
        assert acc.segments() == []
        assert acc.text() == ""

    def test_add_single_segment(self):
        acc = SegmentAccumulator()
        evt = self._make_event("seg-0", text="Hello.")
        acc.add(evt)
        assert acc.session_id == "sess-acc"
        segs = acc.segments()
        assert len(segs) == 1
        assert segs[0].segment_id == "seg-0"
        assert acc.text() == "Hello."

    def test_ordering_by_start_ms_and_sequence_id(self):
        acc = SegmentAccumulator()
        # Add out of order: start_ms = 2000, 0, 1000
        acc.add(self._make_event("seg-2", sequence_id=2, start_ms=2000, text="three."))
        acc.add(self._make_event("seg-0", sequence_id=0, start_ms=0, text="one"))
        acc.add(self._make_event("seg-1", sequence_id=1, start_ms=1000, text="two"))

        segs = acc.segments()
        assert [s.segment_id for s in segs] == ["seg-0", "seg-1", "seg-2"]
        assert acc.text() == "one two three."

    def test_interim_replaced_by_final_segment(self):
        acc = SegmentAccumulator()
        # 1. Interim segment
        interim = self._make_event(
            "seg-0", text="Hel...", is_final=False, confidence=0.5
        )
        acc.add(interim)
        assert acc.segments()[0].is_final is False
        assert acc.text() == "Hel..."

        # 2. Final segment with same segment_id
        final = self._make_event(
            "seg-0", text="Hello world.", is_final=True, confidence=0.99
        )
        acc.add(final)
        segs = acc.segments()
        assert len(segs) == 1
        assert segs[0].is_final is True
        assert segs[0].text == "Hello world."
        assert segs[0].confidence == 0.99
        assert acc.text() == "Hello world."

    def test_final_cannot_regress_to_interim(self):
        acc = SegmentAccumulator()
        final = self._make_event("seg-0", text="Final text.", is_final=True)
        acc.add(final)

        # Attempt to add interim with same segment_id
        interim = self._make_event("seg-0", text="Regressed text?", is_final=False)
        acc.add(interim)

        segs = acc.segments()
        assert len(segs) == 1
        assert segs[0].is_final is True
        assert segs[0].text == "Final text."

    def test_duplicate_final_segments_suppressed(self):
        acc = SegmentAccumulator()
        final = self._make_event("seg-0", text="Repeated text.", is_final=True)
        acc.add(final)
        acc.add(final)
        acc.add(final)

        segs = acc.segments()
        assert len(segs) == 1
        assert segs[0].text == "Repeated text."

    def test_multiple_interim_updates(self):
        acc = SegmentAccumulator()
        acc.add(self._make_event("seg-0", text="Draft 1", is_final=False))
        acc.add(self._make_event("seg-0", text="Draft 2", is_final=False))
        segs = acc.segments()
        assert len(segs) == 1
        assert segs[0].text == "Draft 2"
        assert segs[0].is_final is False

    def test_error_events_do_not_become_segments(self):
        acc = SegmentAccumulator()
        err_payload = ErrorEnvelope(
            code="TRANSCRIPTION_ERROR",
            message_safe_for_user="Error occurred",
            retryable=False,
            correlation_id="c1",
        )
        err_event = TranscriptEvent(
            event_id="evt-err-1",
            event_type="transcript.error",
            schema_version="1.0",
            session_id="sess-acc",
            correlation_id="c1",
            timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            producer="transcription",
            payload=err_payload,
        )
        acc.add(err_event)
        assert acc.segments() == []

    def test_reject_mixed_sessions(self):
        acc = SegmentAccumulator()
        acc.add(self._make_event("seg-0", session_id="sess-A"))
        with pytest.raises(ValueError, match="Cannot add event with session_id"):
            acc.add(self._make_event("seg-1", session_id="sess-B"))

    def test_non_transcript_event_raises_type_error(self):
        acc = SegmentAccumulator()
        with pytest.raises(
            TypeError, match="event must be an instance of TranscriptEvent"
        ):
            acc.add("not an event")  # type: ignore

    def test_clear_resets_accumulator(self):
        acc = SegmentAccumulator()
        acc.add(self._make_event("seg-0", session_id="sess-1"))
        assert len(acc.segments()) == 1
        acc.clear()
        assert acc.session_id is None
        assert acc.segments() == []
