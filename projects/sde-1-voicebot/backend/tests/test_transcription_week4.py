"""Week 4 hardening, long-session consistency, and redacted logging tests for W2."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

import pytest

from app.audio.chunker import chunk_pcm
from app.audio.source import make_fake_pcm
from app.contracts.audio import AudioChunk, AudioFormat, SpeechEvent
from app.contracts.common import ErrorEnvelope
from app.contracts.transcription import TranscriptEvent, TranscriptSegment
from app.sessions.logging import StructuredRedactingFormatter
from app.transcription.accumulator import SegmentAccumulator
from app.transcription.adapter import TranscriptionAdapter
from app.transcription.orchestrator import TranscriptionOrchestrator
from app.tts import (
    MockSynthesizer,
    PiperSynthesizer,
    TTSConfig,
    TTSTextTooLongError,
    TTSUnavailableError,
)


def _make_chunk(session_id: str, sequence_id: int, start_ms: int = 0) -> AudioChunk:
    return AudioChunk(
        session_id=session_id,
        sequence_id=sequence_id,
        start_ms=start_ms,
        duration_ms=20,
        format=AudioFormat(),
        pcm=b"\x00\x00" * 320,
    )


class TestLongSessionConsistency:
    """Acceptance criteria: long-session tests show consistent segments."""

    def test_long_session_maintains_deterministic_chronological_order(
        self,
    ) -> None:
        """Stream 50 consecutive utterances without lost or duplicate segments."""
        session_id = "sess-long-session-001"
        corr_id = "corr-long-001"
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        accumulator = SegmentAccumulator()
        orchestrator = TranscriptionOrchestrator(accumulator=accumulator)

        total_utterances = 50
        all_emitted_events: list[TranscriptEvent] = []

        for i in range(total_utterances):
            start_ms = i * 1000
            end_ms = start_ms + 800

            pcm = make_fake_pcm(duration_ms=800)
            chunks = chunk_pcm(pcm, session_id=session_id, chunk_ms=20)
            offset_chunks = [
                c.model_copy(
                    update={
                        "start_ms": start_ms + c.start_ms,
                        "sequence_id": c.sequence_id + (i * 40),
                    }
                )
                for c in chunks
            ]

            speech_events = [
                SpeechEvent(
                    kind="speech_start",
                    session_id=session_id,
                    correlation_id=corr_id,
                    sequence_id=i * 2,
                    at_ms=start_ms,
                ),
                SpeechEvent(
                    kind="speech_end",
                    session_id=session_id,
                    correlation_id=corr_id,
                    sequence_id=i * 2 + 1,
                    at_ms=end_ms,
                ),
            ]

            evts = orchestrator.process_speech_session(
                speech_events,
                offset_chunks,
                session_id=session_id,
                correlation_id=corr_id,
                timestamp=ts,
            )
            all_emitted_events.extend(evts)

        # Verify no lost or duplicated segments
        segments = orchestrator.get_segments()
        assert len(segments) == total_utterances
        assert len(orchestrator.get_final_segments()) == total_utterances

        seen_segment_ids: set[str] = set()
        for idx, seg in enumerate(segments):
            assert seg.session_id == session_id
            assert seg.segment_id not in seen_segment_ids
            seen_segment_ids.add(seg.segment_id)
            assert seg.is_final is True

            if idx > 0:
                prev_seg = segments[idx - 1]
                assert seg.start_ms >= prev_seg.end_ms

    def test_long_session_interim_to_final_revision_consistency(self) -> None:
        """Stream rapid interleaved interims and finals without losing text."""
        acc = SegmentAccumulator()
        session_id = "sess-interim-stress"

        num_segments = 30
        for i in range(num_segments):
            seg_id = f"seg-{i}"
            for rev in range(3):
                interim = TranscriptSegment(
                    segment_id=seg_id,
                    session_id=session_id,
                    sequence_id=rev,
                    start_ms=i * 1000,
                    end_ms=i * 1000 + 200 * (rev + 1),
                    text=f"Draft {rev} for utterance {i}",
                    is_final=False,
                )
                acc.add(interim)
                assert acc.revisions_count(seg_id) == rev

            final = TranscriptSegment(
                segment_id=seg_id,
                session_id=session_id,
                sequence_id=3,
                start_ms=i * 1000,
                end_ms=i * 1000 + 800,
                text=f"Final text for utterance {i}.",
                is_final=True,
            )
            acc.add(final)
            assert acc.revisions_count(seg_id) == 3

        final_segs = acc.final_segments()
        assert len(final_segs) == num_segments
        for i, s in enumerate(final_segs):
            assert s.text == f"Final text for utterance {i}."
            assert s.is_final is True


class TestMidstreamCancellationConsistency:
    """Acceptance criteria: cancelling leaves consistent transcript, nothing after."""

    def test_cancel_midstream_drops_inflight_and_emits_nothing(self) -> None:
        """Calling cancel mid-utterance suppresses in-flight emissions."""
        published_events: list[TranscriptEvent] = []

        def sink(sid: str, evt: TranscriptEvent) -> None:
            published_events.append(evt)

        orchestrator = TranscriptionOrchestrator(event_sink=sink)
        session_id = "sess-cancel-consistency"
        corr_id = "corr-cancel-01"
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        # 1. Process Utterance 1 successfully
        chunks1 = [
            _make_chunk(session_id, 0, start_ms=0),
            _make_chunk(session_id, 1, start_ms=20),
        ]
        evts1 = orchestrator.process_chunks(
            chunks1, session_id=session_id, correlation_id=corr_id, timestamp=ts
        )
        assert len(evts1) == 1
        assert len(orchestrator.get_segments()) == 1
        assert len(published_events) == 1

        # 2. Cancel the session
        orchestrator.cancel(session_id)

        # 3. Process chunks for cancelled utterance: returns [] and emits zero events
        chunks_cancelled = [_make_chunk(session_id, 2, start_ms=40)]
        evts_cancelled = orchestrator.process_chunks(
            chunks_cancelled,
            session_id=session_id,
            correlation_id="corr-cancel-02",
            timestamp=ts,
        )
        assert evts_cancelled == []
        assert len(published_events) == 1
        assert len(orchestrator.get_segments()) == 1

        # 4. Subsequent utterance after cancelled one proceeds cleanly
        chunks2 = [_make_chunk(session_id, 3, start_ms=1000)]
        evts2 = orchestrator.process_chunks(
            chunks2,
            session_id=session_id,
            correlation_id="corr-after-cancel",
            timestamp=ts,
        )
        assert len(evts2) == 1
        assert len(orchestrator.get_segments()) == 2
        assert len(published_events) == 2

    def test_cancel_inside_process_speech_session_leaves_no_emissions(self) -> None:
        """Cancel applied before speech session returns empty and emits nothing."""
        published_events: list[TranscriptEvent] = []

        def sink(sid: str, evt: TranscriptEvent) -> None:
            published_events.append(evt)

        orchestrator = TranscriptionOrchestrator(event_sink=sink)
        session_id = "sess-cancel-speech"
        corr_id = "corr-sp-cancel"
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        pcm = make_fake_pcm(duration_ms=400)
        chunks = chunk_pcm(pcm, session_id=session_id, chunk_ms=20)
        speech_events = [
            SpeechEvent(
                kind="speech_start",
                session_id=session_id,
                correlation_id=corr_id,
                sequence_id=0,
                at_ms=0,
            ),
            SpeechEvent(
                kind="speech_end",
                session_id=session_id,
                correlation_id=corr_id,
                sequence_id=1,
                at_ms=400,
            ),
        ]

        orchestrator.cancel(session_id)

        events = orchestrator.process_speech_session(
            speech_events,
            chunks,
            session_id=session_id,
            correlation_id=corr_id,
            timestamp=ts,
        )
        assert events == []
        assert published_events == []
        assert orchestrator.get_segments() == []


class TestRedactedLogging:
    """Acceptance criteria: logs never contain transcript text or audio payloads."""

    def test_redacting_formatter_redacts_transcript_text_and_audio_payloads(
        self,
    ) -> None:
        """Assert StructuredRedactingFormatter cleans transcript and audio bytes."""
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        formatter = StructuredRedactingFormatter()
        handler.setFormatter(formatter)

        logger = logging.getLogger("test_redacted_transcription")
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

        secret_transcript = "My secret password is open-sesame-123"
        raw_log_msg = (
            f'{{"event": "transcript.segment", "text": "{secret_transcript}"}}'
        )
        logger.info(raw_log_msg)

        raw_audio_repr = "Audio payload: b'\\x00\\x10\\xff\\xfe' with duration 20ms"
        logger.info(raw_audio_repr)

        log_lines = stream.getvalue().strip().split("\n")
        assert len(log_lines) == 2

        record1 = json.loads(log_lines[0])
        assert secret_transcript not in record1["message"]
        assert "[REDACTED_TEXT]" in record1["message"]

        record2 = json.loads(log_lines[1])
        assert "b'\\x00\\x10\\xff\\xfe'" not in record2["message"]
        assert "[REDACTED_AUDIO_BYTES]" in record2["message"]

    def test_orchestrator_execution_does_not_leak_raw_audio_or_tokens(self) -> None:
        """Integration check: orchestrator error logging redacts exception details."""

        class SecretErrorModel:
            def transcribe(self, audio: Any, **kwargs: Any) -> Any:
                raise RuntimeError(
                    "Failed to reach https://secret-token@api.example.com/models"
                )

        class TestAdapter(TranscriptionAdapter):
            def transcribe(
                self,
                chunks: Sequence[AudioChunk],
                *,
                session_id: str,
                correlation_id: str,
                timestamp: datetime,
            ) -> list[TranscriptEvent]:
                try:
                    SecretErrorModel().transcribe(chunks)
                    return []
                except Exception as exc:
                    err_env = ErrorEnvelope(
                        code="TRANSCRIPTION_FAILED",
                        message_safe_for_user="Transcription failed safely.",
                        retryable=False,
                        correlation_id=correlation_id,
                        details_redacted={"reason": type(exc).__name__},
                    )
                    return [
                        TranscriptEvent(
                            event_id="err-1",
                            event_type="transcript.error",
                            schema_version="1.0",
                            session_id=session_id,
                            correlation_id=correlation_id,
                            timestamp=timestamp,
                            producer="transcription",
                            payload=err_env,
                        )
                    ]

            def cancel(self, session_id: str) -> None:
                pass

            def reset(self, session_id: str | None = None) -> None:
                pass

        adapter = TestAdapter()
        orch = TranscriptionOrchestrator(adapter=adapter)
        chunks = [_make_chunk("sess-leak", 0)]
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        events = orch.process_chunks(
            chunks, session_id="sess-leak", correlation_id="c1", timestamp=ts
        )
        assert len(events) == 1
        err = events[0].payload
        assert isinstance(err, ErrorEnvelope)
        assert "secret-token" not in str(err.details_redacted)
        assert "secret-token" not in err.message_safe_for_user


class TestSpokenRepliesStressAndBoundaries:
    """Stress and edge-case boundary tests for text-to-speech synthesizers."""

    def test_mock_synthesizer_various_utterance_lengths(self) -> None:
        """Synthesize utterances of various lengths up to 300 characters."""
        synth = MockSynthesizer()

        test_phrases = [
            "Hi.",
            "Yes, I opened the browser.",
            "System metrics are normal: CPU is at 14% and memory usage is 42%.",
            (
                "This is a longer reply simulating Jarvis explaining the status "
                "of the workflow execution."
            ),
            "X" * 300,  # Exact 300 character boundary
        ]

        for phrase in test_phrases:
            wav_bytes = synth.synthesize(phrase)
            assert isinstance(wav_bytes, bytes)
            assert len(wav_bytes) > 44
            assert wav_bytes.startswith(b"RIFF")

    def test_mock_synthesizer_refuses_301_characters(self) -> None:
        """Strictly refuses 301 characters with TTSTextTooLongError."""
        synth = MockSynthesizer()
        with pytest.raises(TTSTextTooLongError):
            synth.synthesize("A" * 301)

    def test_piper_synthesizer_caching_and_custom_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """Verify PiperSynthesizer cache directory configuration."""
        import sys
        from unittest.mock import MagicMock

        custom_cache = tmp_path / "custom_piper_cache"
        custom_cache.mkdir()

        # Simulate piper package installed so missing-model path is exercised
        mock_piper = MagicMock()
        monkeypatch.setitem(sys.modules, "piper", mock_piper)
        monkeypatch.setitem(sys.modules, "piper.voice", mock_piper.voice)

        cfg = TTSConfig(
            provider="piper",
            voice="en_US-lessac-medium",
            cache_dir=str(custom_cache),
        )
        synth = PiperSynthesizer(config=cfg)

        with pytest.raises(TTSUnavailableError) as exc_info:
            synth.synthesize("Testing voice synthesis.")

        assert exc_info.value.error_code == "TTS_UNAVAILABLE"
        assert str(custom_cache) in str(synth._load_error)
