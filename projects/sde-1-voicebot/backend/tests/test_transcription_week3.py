"""Tests for Week 3 Speech-to-Text: revisions, confidence, and stream."""

import io
import sys
import wave
from datetime import datetime, timezone
from typing import Any

import pytest

from app.audio.chunker import chunk_pcm
from app.audio.source import make_fake_pcm
from app.contracts.audio import AudioChunk, AudioFormat, SpeechEvent
from app.contracts.common import ErrorEnvelope
from app.contracts.transcription import TranscriptEvent, TranscriptSegment
from app.transcription.accumulator import SegmentAccumulator
from app.transcription.config import TranscriptionConfig
from app.transcription.faster_whisper import FasterWhisperAdapter
from app.transcription.mock import FakeTranscriber
from app.transcription.orchestrator import TranscriptionOrchestrator


def _make_chunk(
    session_id: str,
    seq: int,
    start_ms: int = 0,
    duration_ms: int = 20,
) -> AudioChunk:
    return AudioChunk(
        session_id=session_id,
        sequence_id=seq,
        start_ms=start_ms,
        duration_ms=duration_ms,
        format=AudioFormat(),
        pcm=bytes(duration_ms * 32),
    )


def _make_segment(
    segment_id: str,
    *,
    session_id: str = "sess-w3",
    sequence_id: int = 0,
    start_ms: int = 0,
    end_ms: int = 1000,
    text: str = "Test utterance",
    confidence: float = 0.95,
    is_final: bool = True,
) -> TranscriptSegment:
    return TranscriptSegment(
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


def _make_event(segment: TranscriptSegment) -> TranscriptEvent:
    return TranscriptEvent(
        event_id=f"evt-{segment.segment_id}-{segment.sequence_id}",
        event_type="transcript.segment",
        schema_version="1.0",
        session_id=segment.session_id,
        correlation_id="corr-w3",
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        producer="transcription",
        payload=segment,
    )


class TestRevisionsAndFinalization:
    """Interim segments revised, exactly one final closes, session-aware."""

    def test_interim_segment_revised_and_finalized_with_clear_events(self) -> None:
        acc = SegmentAccumulator()
        # 1. First interim draft
        interim1 = _make_segment(
            "seg-0",
            sequence_id=0,
            text="Open the brow",
            is_final=False,
            confidence=0.75,
        )
        assert acc.add(interim1) is True
        assert acc.revisions_count("seg-0") == 0
        assert acc.text() == "Open the brow"
        assert acc.final_segments() == []

        # 2. Revised interim draft
        interim2 = _make_segment(
            "seg-0",
            sequence_id=1,
            text="Open the browser",
            is_final=False,
            confidence=0.82,
        )
        assert acc.add(interim2) is True
        assert acc.revisions_count("seg-0") == 1
        assert acc.text() == "Open the browser"
        assert acc.final_segments() == []

        # 3. Final event closes the segment
        final_seg = _make_segment(
            "seg-0",
            sequence_id=2,
            text="Open the browser.",
            is_final=True,
            confidence=0.96,
        )
        assert acc.add(final_seg) is True
        assert acc.revisions_count("seg-0") == 2
        assert len(acc.final_segments()) == 1
        assert acc.final_segments()[0].text == "Open the browser."
        assert acc.final_segments()[0].is_final is True

        # 4. Final cannot regress to interim or accept late mutations
        late_interim = _make_segment(
            "seg-0",
            sequence_id=3,
            text="Late interim ignored",
            is_final=False,
        )
        assert acc.add(late_interim) is False
        assert acc.text() == "Open the browser."

    def test_every_transcript_event_carries_matching_session_id(self) -> None:
        seg = _make_segment("seg-sess", session_id="session-user-42")
        evt = _make_event(seg)
        assert evt.session_id == "session-user-42"
        assert evt.payload.session_id == "session-user-42"

        # Envelope validation rejects mismatched session ID
        with pytest.raises(ValueError, match="payload session_id .* must match"):
            TranscriptEvent(
                event_id="evt-mismatch",
                event_type="transcript.segment",
                schema_version="1.0",
                session_id="session-other",
                correlation_id="corr-w3",
                timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                producer="transcription",
                payload=seg,
            )


class TestConfidenceThresholdHandling:
    """Low-confidence segments handled by configurable threshold."""

    def test_low_confidence_segments_never_sent_as_final_text_without_flag(
        self,
    ) -> None:
        acc = SegmentAccumulator(confidence_threshold=0.4)

        # High confidence segment (0.85 >= 0.4)
        high_conf = _make_segment(
            "seg-high",
            sequence_id=0,
            start_ms=0,
            end_ms=1000,
            text="High confidence phrase",
            confidence=0.85,
            is_final=True,
        )
        # Low confidence segment (0.25 < 0.4)
        low_conf = _make_segment(
            "seg-low",
            sequence_id=1,
            start_ms=1000,
            end_ms=2000,
            text="mumbled noise",
            confidence=0.25,
            is_final=True,
        )

        acc.add(high_conf)
        acc.add(low_conf)

        # By default, final_segments() excludes low-confidence segments
        finals = acc.final_segments(include_low_confidence=False)
        assert [s.segment_id for s in finals] == ["seg-high"]
        assert acc.final_text(include_low_confidence=False) == "High confidence phrase"

        # Explicitly requested, low-confidence segments can be inspected
        all_finals = acc.final_segments(include_low_confidence=True)
        assert [s.segment_id for s in all_finals] == ["seg-high", "seg-low"]
        assert acc.low_confidence_segments() == [low_conf]
        assert (
            acc.final_text(include_low_confidence=True)
            == "High confidence phrase mumbled noise"
        )

    def test_configurable_confidence_threshold(self) -> None:
        # Custom threshold of 0.7
        acc = SegmentAccumulator(confidence_threshold=0.7)
        mid_conf = _make_segment(
            "seg-mid",
            confidence=0.65,
            is_final=True,
        )
        acc.add(mid_conf)
        assert acc.is_low_confidence(mid_conf) is True
        assert acc.final_segments() == []
        assert acc.final_segments(include_low_confidence=True) == [mid_conf]

    def test_confidence_threshold_validation(self) -> None:
        """Validate confidence threshold is a valid float in [0.0, 1.0]."""
        with pytest.raises(
            ValueError, match="confidence_threshold must be a float between 0.0 and 1.0"
        ):
            SegmentAccumulator(confidence_threshold=-0.1)

        with pytest.raises(
            ValueError, match="confidence_threshold must be a float between 0.0 and 1.0"
        ):
            SegmentAccumulator(confidence_threshold=1.5)

        with pytest.raises(
            ValueError, match="confidence_threshold must be a float between 0.0 and 1.0"
        ):
            TranscriptionConfig(confidence_threshold=-0.5)

        with pytest.raises(
            ValueError, match="confidence_threshold must be a float between 0.0 and 1.0"
        ):
            TranscriptionConfig(confidence_threshold=2.0)


class TestCancellationAndFailureRecovery:
    """Cancellation stops transcription cleanly, fallback to mock."""

    def test_cancellation_stops_inflight_transcription_and_emits_no_events(
        self,
    ) -> None:
        orchestrator = TranscriptionOrchestrator()
        chunks = [_make_chunk("sess-cancel", i) for i in range(5)]
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        # Before cancellation: emits transcript events
        evts = orchestrator.process_chunks(
            chunks, session_id="sess-cancel", correlation_id="c1", timestamp=ts
        )
        assert len(evts) == 1

        # Cancel session
        orchestrator.cancel("sess-cancel")

        # After cancellation: emits zero events
        evts_after = orchestrator.process_chunks(
            chunks, session_id="sess-cancel", correlation_id="c2", timestamp=ts
        )
        assert evts_after == []

    def test_faster_whisper_load_failure_falls_back_to_mock_with_normalized_error(
        self,
    ) -> None:
        config = TranscriptionConfig(provider="faster_whisper", fallback_to_mock=True)
        # FasterWhisperAdapter with no faster_whisper package / model failure
        adapter = FasterWhisperAdapter(config=config)
        chunks = [_make_chunk("sess-fallback", 0)]
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        events = adapter.transcribe(
            chunks, session_id="sess-fallback", correlation_id="c-fb", timestamp=ts
        )

        # Normalized fallback error followed by mock transcript segment
        assert len(events) >= 2
        assert events[0].event_type == "transcript.error"
        err = events[0].payload
        assert isinstance(err, ErrorEnvelope)
        assert err.code == "TRANSCRIPTION_FALLBACK_TO_MOCK"
        assert err.retryable is False

        # Session continues cleanly via mock transcriber
        assert events[1].event_type == "transcript.segment"
        assert events[1].payload.session_id == "sess-fallback"
        assert events[1].payload.text == "Hello from the mock voicebot."

    def test_faster_whisper_error_without_fallback_redacts_raw_exception(
        self,
    ) -> None:
        """Raw exception messages and paths must not leak when fallback is disabled."""

        class FailingModel:
            def transcribe(self, audio: Any, **kwargs: Any) -> Any:
                raise RuntimeError(r"C:\Users\megha\models secret-token-123")

        config = TranscriptionConfig(provider="faster_whisper", fallback_to_mock=False)
        adapter = FasterWhisperAdapter(config=config, model=FailingModel())
        chunks = [_make_chunk("sess-leak-check", 0)]
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        events = adapter.transcribe(
            chunks,
            session_id="sess-leak-check",
            correlation_id="c-leak",
            timestamp=ts,
        )

        assert len(events) == 1
        assert events[0].event_type == "transcript.error"
        err = events[0].payload
        assert isinstance(err, ErrorEnvelope)
        assert err.code == "TRANSCRIPTION_PROVIDER_ERROR"
        assert err.details_redacted is not None
        assert err.details_redacted.get("reason") == "RuntimeError"
        # Assert raw exception text/tokens never leak into details or message
        assert "secret-token-123" not in str(err.details_redacted)
        assert "secret-token-123" not in err.message_safe_for_user

    def test_faster_whisper_caches_failed_model_load(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Failed model load is cached so subsequent calls don't retry repeatedly."""
        load_attempts = 0

        def failing_whisper_model(*args: Any, **kwargs: Any) -> Any:
            nonlocal load_attempts
            load_attempts += 1
            raise RuntimeError("Failed to load WhisperModel from network")

        import sys

        # Mock the faster_whisper import inside faster_whisper.py
        class MockModule:
            WhisperModel = staticmethod(failing_whisper_model)

        monkeypatch.setitem(sys.modules, "faster_whisper", MockModule)

        config = TranscriptionConfig(provider="faster_whisper", fallback_to_mock=False)
        adapter = FasterWhisperAdapter(config=config)
        chunks = [_make_chunk("sess-cache-test", 0)]
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        # First call triggers load attempt
        adapter.transcribe(
            chunks, session_id="sess-cache-test", correlation_id="c1", timestamp=ts
        )
        assert load_attempts == 1
        assert adapter.health() == "degraded"

        # Second call uses cached _load_error and must NOT attempt loading again
        adapter.transcribe(
            chunks, session_id="sess-cache-test", correlation_id="c2", timestamp=ts
        )
        assert load_attempts == 1

    def test_error_event_ids_unique_across_calls(self) -> None:
        """Every error/fallback event must carry a globally unique event ID."""
        # 1. FakeTranscriber error IDs
        fake = FakeTranscriber(failure_mode="quota_error")
        chunks = [_make_chunk("sess-unique-err", 0)]
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        evts1 = fake.transcribe(
            chunks, session_id="sess-unique-err", correlation_id="c1", timestamp=ts
        )
        evts2 = fake.transcribe(
            chunks, session_id="sess-unique-err", correlation_id="c2", timestamp=ts
        )
        assert evts1[0].event_id != evts2[0].event_id

        # 2. FasterWhisperAdapter error IDs without fallback
        class ErrModel:
            def transcribe(self, audio: Any, **kwargs: Any) -> Any:
                raise RuntimeError("engine failure")

        adapter_no_fb = FasterWhisperAdapter(
            config=TranscriptionConfig(fallback_to_mock=False),
            model=ErrModel(),
        )
        a_evts1 = adapter_no_fb.transcribe(
            chunks, session_id="sess-unique-err", correlation_id="c1", timestamp=ts
        )
        a_evts2 = adapter_no_fb.transcribe(
            chunks, session_id="sess-unique-err", correlation_id="c2", timestamp=ts
        )
        assert a_evts1[0].event_id != a_evts2[0].event_id

        # 3. FasterWhisperAdapter fallback error IDs with fallback enabled
        adapter_fb = FasterWhisperAdapter(
            config=TranscriptionConfig(fallback_to_mock=True),
            model=ErrModel(),
        )
        fb_evts1 = adapter_fb.transcribe(
            chunks, session_id="sess-unique-err", correlation_id="c1", timestamp=ts
        )
        fb_evts2 = adapter_fb.transcribe(
            chunks, session_id="sess-unique-err", correlation_id="c2", timestamp=ts
        )
        assert fb_evts1[0].event_id != fb_evts2[0].event_id

    def test_faster_whisper_quota_network_failure_handling(
        self,
    ) -> None:
        """Test real-provider fallback to mock on quota and network model failures."""

        class QuotaExceededError(Exception):
            pass

        class ModelNetworkConnectionError(Exception):
            pass

        class FailingModel:
            def __init__(self, exc: Exception) -> None:
                self.exc = exc

            def transcribe(self, audio: Any, **kwargs: Any) -> Any:
                raise self.exc

        chunks = [_make_chunk("sess-err-fallback", 0)]
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        # 1. Quota error with fallback_to_mock=True
        cfg_fb = TranscriptionConfig(provider="faster_whisper", fallback_to_mock=True)
        adapter_q = FasterWhisperAdapter(
            config=cfg_fb,
            model=FailingModel(QuotaExceededError("Rate limit / quota exceeded")),
        )
        events_q = adapter_q.transcribe(
            chunks,
            session_id="sess-err-fallback",
            correlation_id="c-q",
            timestamp=ts,
        )
        assert len(events_q) >= 2
        assert events_q[0].event_type == "transcript.error"
        err_q = events_q[0].payload
        assert isinstance(err_q, ErrorEnvelope)
        assert err_q.code == "TRANSCRIPTION_FALLBACK_TO_MOCK"
        assert err_q.details_redacted is not None
        assert err_q.details_redacted["reason"] == "QuotaExceededError"
        assert events_q[1].event_type == "transcript.segment"
        assert events_q[1].payload.text == "Hello from the mock voicebot."

        # 2. Network error with fallback_to_mock=True
        adapter_n = FasterWhisperAdapter(
            config=cfg_fb,
            model=FailingModel(ModelNetworkConnectionError("Connection timed out")),
        )
        events_n = adapter_n.transcribe(
            chunks,
            session_id="sess-err-fallback",
            correlation_id="c-n",
            timestamp=ts,
        )
        assert len(events_n) >= 2
        assert events_n[0].event_type == "transcript.error"
        err_n = events_n[0].payload
        assert isinstance(err_n, ErrorEnvelope)
        assert err_n.code == "TRANSCRIPTION_FALLBACK_TO_MOCK"
        assert err_n.details_redacted is not None
        assert err_n.details_redacted["reason"] == "ModelNetworkConnectionError"
        assert events_n[1].event_type == "transcript.segment"

        # 3. Network error with fallback_to_mock=False (no raw leak)
        cfg_no_fb = TranscriptionConfig(
            provider="faster_whisper", fallback_to_mock=False
        )
        adapter_no_fb = FasterWhisperAdapter(
            config=cfg_no_fb,
            model=FailingModel(
                ModelNetworkConnectionError("internal-endpoint:8080/private-key-456")
            ),
        )
        events_no_fb = adapter_no_fb.transcribe(
            chunks,
            session_id="sess-err-fallback",
            correlation_id="c-no-fb",
            timestamp=ts,
        )
        assert len(events_no_fb) == 1
        assert events_no_fb[0].event_type == "transcript.error"
        err_no_fb = events_no_fb[0].payload
        assert isinstance(err_no_fb, ErrorEnvelope)
        assert err_no_fb.code == "TRANSCRIPTION_PROVIDER_ERROR"
        assert err_no_fb.details_redacted["reason"] == "ModelNetworkConnectionError"
        assert "private-key-456" not in str(err_no_fb.details_redacted)

    def test_transcription_config_device_and_compute_resolution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TranscriptionConfig resolves device and compute respecting CUDA."""
        import torch

        # Test CUDA auto-detection
        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        cfg_cuda = TranscriptionConfig(device="auto", compute_type="auto")
        assert cfg_cuda.resolve_device_and_compute() == ("cuda", "float16")

        # Test CPU auto-detection
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
        cfg_cpu = TranscriptionConfig(device="auto", compute_type="auto")
        assert cfg_cpu.resolve_device_and_compute() == ("cpu", "int8")

        # Guard against invalid float16 on CPU
        cfg_cpu_f16 = TranscriptionConfig(device="cpu", compute_type="float16")
        assert cfg_cpu_f16.resolve_device_and_compute() == ("cpu", "int8")

    def test_faster_whisper_numpy_missing_wave_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When numpy is not installed, raw PCM is wrapped in valid WAV buffer."""
        adapter = FasterWhisperAdapter()
        pcm = bytes(3200)  # 100ms 16kHz 16-bit mono PCM

        # Hide numpy to force fallback to standard library wave module
        monkeypatch.setitem(sys.modules, "numpy", None)

        result = adapter._prepare_audio_input(pcm)
        assert isinstance(result, io.BytesIO)
        result.seek(0)
        with wave.open(result, "rb") as wav_file:
            assert wav_file.getnchannels() == 1
            assert wav_file.getsampwidth() == 2
            assert wav_file.getframerate() == 16000
            frames = wav_file.readframes(1600)
            assert frames == pcm

    def test_quota_failure_falls_back_with_normalized_error(self) -> None:
        transcriber = FakeTranscriber(failure_mode="quota_error")
        chunks = [_make_chunk("sess-quota", 0)]
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        events = transcriber.transcribe(
            chunks, session_id="sess-quota", correlation_id="c-q", timestamp=ts
        )
        assert len(events) == 1
        assert events[0].event_type == "transcript.error"
        err = events[0].payload
        assert isinstance(err, ErrorEnvelope)
        assert err.code == "TRANSCRIPTION_QUOTA_EXCEEDED"
        assert err.retryable is False

    def test_network_failure_returns_retryable_error(self) -> None:
        transcriber = FakeTranscriber(failure_mode="network_error")
        chunks = [_make_chunk("sess-net", 0)]
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        events = transcriber.transcribe(
            chunks, session_id="sess-net", correlation_id="c-net", timestamp=ts
        )
        assert len(events) == 1
        assert events[0].event_type == "transcript.error"
        err = events[0].payload
        assert isinstance(err, ErrorEnvelope)
        assert err.code == "TRANSCRIPTION_NETWORK_ERROR"
        assert err.retryable is True


class TestFasterWhisperMapping:
    """Acceptance criteria: FasterWhisperAdapter maps model segments correctly."""

    def test_faster_whisper_maps_model_segments_correctly(self) -> None:
        class FakeModelSegment:
            def __init__(
                self,
                start: float,
                end: float,
                text: str,
                confidence: float,
            ) -> None:
                self.start = start
                self.end = end
                self.text = text
                self.confidence = confidence

        class FakeWhisperModel:
            def transcribe(self, audio: Any, **kwargs: Any) -> tuple[list[Any], Any]:
                segs = [
                    FakeModelSegment(0.0, 1.2, "Hey Jarvis", 0.98),
                    FakeModelSegment(1.2, 3.5, "look at my code", 0.91),
                ]
                return segs, None

        adapter = FasterWhisperAdapter(model=FakeWhisperModel())
        chunks = [
            _make_chunk("sess-fw", 0, start_ms=1000, duration_ms=20),
            _make_chunk("sess-fw", 1, start_ms=1020, duration_ms=20),
        ]
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        events = adapter.transcribe(
            chunks, session_id="sess-fw", correlation_id="c-fw", timestamp=ts
        )

        assert len(events) == 2
        # Verify segment 1 mapping
        s1 = events[0].payload
        assert isinstance(s1, TranscriptSegment)
        assert s1.segment_id == "sess-fw-fw-0"
        assert s1.text == "Hey Jarvis"
        assert s1.start_ms == 1000  # stream_base_ms + 0
        assert s1.end_ms == 2200  # stream_base_ms + 1200
        assert s1.confidence == 0.98
        assert s1.is_final is True

        # Verify segment 2 mapping
        s2 = events[1].payload
        assert isinstance(s2, TranscriptSegment)
        assert s2.segment_id == "sess-fw-fw-1"
        assert s2.text == "look at my code"
        assert s2.start_ms == 2200  # stream_base_ms + 1200
        assert s2.end_ms == 4500  # stream_base_ms + 3500
        assert s2.confidence == 0.91
        assert s2.is_final is True


class TestSpeechEventsAndEventStreamIntegration:
    """Acceptance criteria: speech boundaries consumed, events published to stream."""

    def test_consumes_w1_speech_event_boundaries_as_one_utterance(self) -> None:
        orchestrator = TranscriptionOrchestrator()
        session_id = "sess-speech-e2e"
        corr_id = "corr-speech-e2e"
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        # Chunks: 0..1000ms (50 chunks of 20ms)
        pcm = make_fake_pcm(duration_ms=1000)
        chunks = chunk_pcm(pcm, session_id=session_id, chunk_ms=20)

        # W1 SpeechEvents: wake at 0ms, speech_start at 100ms, speech_end at 700ms
        speech_events = [
            SpeechEvent(
                kind="wake",
                session_id=session_id,
                correlation_id=corr_id,
                sequence_id=0,
                at_ms=0,
                wake_word="hey_jarvis",
                score=0.95,
            ),
            SpeechEvent(
                kind="speech_start",
                session_id=session_id,
                correlation_id=corr_id,
                sequence_id=1,
                at_ms=100,
            ),
            SpeechEvent(
                kind="speech_end",
                session_id=session_id,
                correlation_id=corr_id,
                sequence_id=2,
                at_ms=700,
            ),
        ]

        events = orchestrator.process_speech_session(
            speech_events,
            chunks,
            session_id=session_id,
            correlation_id=corr_id,
            timestamp=ts,
        )

        assert len(events) == 1
        seg = events[0].payload
        assert isinstance(seg, TranscriptSegment)
        assert seg.session_id == session_id
        # Range should be bounded by speech window [100ms .. 700ms]
        assert seg.start_ms == 100
        assert seg.end_ms >= 700

    def test_publishes_transcript_events_to_session_event_stream(self) -> None:
        """Integration with real W5 SessionService event sink."""
        from app.sessions.service import SessionService

        service = SessionService()
        session_id = "sess-stream-w5"
        service.create_session(session_id)

        orchestrator = TranscriptionOrchestrator(event_sink=service.add_event)
        chunks = [_make_chunk(session_id, 0)]
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        events = orchestrator.process_chunks(
            chunks, session_id=session_id, correlation_id="c-stream", timestamp=ts
        )

        assert len(events) == 1
        recorded_events = service.get_events(session_id)
        assert len(recorded_events) == 1
        recorded_evt = recorded_events[0]
        assert recorded_evt.session_id == session_id
        assert recorded_evt.event_type == "transcript.segment"
        assert recorded_evt.payload.session_id == session_id
        assert recorded_evt.payload.text == "Hello from the mock voicebot."

    def test_process_speech_session_handles_multiple_utterances_without_merging(
        self,
    ) -> None:
        """Speech session pairs speech_start and speech_end into distinct utterances."""
        orchestrator = TranscriptionOrchestrator()
        session_id = "sess-multi-utt"
        corr_id = "corr-multi"
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        pcm = make_fake_pcm(duration_ms=1000)
        chunks = chunk_pcm(pcm, session_id=session_id, chunk_ms=20)

        # Two distinct utterances: [100..300ms] and [500..800ms]
        speech_events = [
            SpeechEvent(
                kind="wake",
                session_id=session_id,
                correlation_id=corr_id,
                sequence_id=0,
                at_ms=0,
                wake_word="hey_jarvis",
                score=0.9,
            ),
            SpeechEvent(
                kind="speech_start",
                session_id=session_id,
                correlation_id=corr_id,
                sequence_id=1,
                at_ms=100,
            ),
            SpeechEvent(
                kind="speech_end",
                session_id=session_id,
                correlation_id=corr_id,
                sequence_id=2,
                at_ms=300,
            ),
            SpeechEvent(
                kind="speech_start",
                session_id=session_id,
                correlation_id=corr_id,
                sequence_id=3,
                at_ms=500,
            ),
            SpeechEvent(
                kind="speech_end",
                session_id=session_id,
                correlation_id=corr_id,
                sequence_id=4,
                at_ms=800,
            ),
        ]

        events = orchestrator.process_speech_session(
            speech_events,
            chunks,
            session_id=session_id,
            correlation_id=corr_id,
            timestamp=ts,
        )

        # Must produce 2 distinct segments, not merged into one
        assert len(events) == 2
        assert events[0].payload.start_ms == 100
        assert events[0].payload.end_ms <= 340
        assert events[1].payload.start_ms == 500
        assert events[1].payload.end_ms <= 840

    def test_process_speech_session_rejects_other_sessions_speech_events(self) -> None:
        """Reject speech events belonging to mismatched sessions."""
        orchestrator = TranscriptionOrchestrator()
        session_id = "sess-target"
        corr_id = "corr-tgt"
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        chunks = [_make_chunk(session_id, 0)]

        foreign_speech_events = [
            SpeechEvent(
                kind="speech_start",
                session_id="sess-foreign",
                correlation_id=corr_id,
                sequence_id=0,
                at_ms=0,
            ),
            SpeechEvent(
                kind="speech_end",
                session_id="sess-foreign",
                correlation_id=corr_id,
                sequence_id=1,
                at_ms=20,
            ),
        ]

        with pytest.raises(
            ValueError,
            match=(
                "Cannot process speech event with session_id 'sess-foreign' "
                "in session 'sess-target'"
            ),
        ):
            orchestrator.process_speech_session(
                foreign_speech_events,
                chunks,
                session_id=session_id,
                correlation_id=corr_id,
                timestamp=ts,
            )


class TestAudioChunkIntegrity:
    """Acceptance criteria: out-of-order and missing chunks produce safe errors."""

    def test_missing_chunks_detected_by_default(self) -> None:
        """Missing chunks detection is active by default without extra config."""
        transcriber = FakeTranscriber()
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        chunk0 = _make_chunk("sess-gap-def", 0, start_ms=0)
        chunk3 = _make_chunk("sess-gap-def", 3, start_ms=60)

        events = transcriber.transcribe(
            [chunk0, chunk3],
            session_id="sess-gap-def",
            correlation_id="c-def",
            timestamp=ts,
        )

        assert len(events) == 1
        assert events[0].event_type == "transcript.error"
        err = events[0].payload
        assert isinstance(err, ErrorEnvelope)
        assert err.code == "TRANSCRIPTION_MISSING_CHUNKS"

    def test_out_of_order_chunks_produce_normalized_error(self) -> None:
        transcriber = FakeTranscriber()
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        # Chunks in inverted order: seq 1 (start 100ms), then seq 0 (start 0ms)
        chunk1 = _make_chunk("sess-ooo", 1, start_ms=100)
        chunk0 = _make_chunk("sess-ooo", 0, start_ms=0)

        events = transcriber.transcribe(
            [chunk1, chunk0],
            session_id="sess-ooo",
            correlation_id="c-ooo",
            timestamp=ts,
        )

        assert len(events) == 1
        assert events[0].event_type == "transcript.error"
        err = events[0].payload
        assert isinstance(err, ErrorEnvelope)
        assert err.code == "TRANSCRIPTION_INVALID_ORDERING"

    def test_missing_chunks_gap_produces_normalized_error(self) -> None:
        transcriber = FakeTranscriber(detect_missing_chunks=True)
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        # Chunks with sequence gap: seq 0, then seq 5 (seqs 1..4 missing)
        chunk0 = _make_chunk("sess-gap", 0, start_ms=0)
        chunk5 = _make_chunk("sess-gap", 5, start_ms=100)

        events = transcriber.transcribe(
            [chunk0, chunk5],
            session_id="sess-gap",
            correlation_id="c-gap",
            timestamp=ts,
        )

        assert len(events) == 1
        assert events[0].event_type == "transcript.error"
        err = events[0].payload
        assert isinstance(err, ErrorEnvelope)
        assert err.code == "TRANSCRIPTION_MISSING_CHUNKS"
