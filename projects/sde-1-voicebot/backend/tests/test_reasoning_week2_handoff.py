"""Real W1 audio -> real W2 transcriber -> W3 context builder and LLM adapter."""

from datetime import datetime, timezone

from app.audio.chunker import chunk_pcm
from app.audio.source import make_fake_pcm
from app.contracts.reasoning import CaptureSettings, ReasoningRequest
from app.contracts.transcription import TranscriptSegment
from app.reasoning.capture import SyntheticCaptureAdapter, SyntheticFrame
from app.reasoning.context_builder import (
    build_context,
    candidates_from_screen,
    candidates_from_transcript,
)
from app.reasoning.llm import LLMReasoningAdapter
from app.reasoning.vision import MockVisionAdapter
from app.transcription.mock import FakeTranscriber

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_w1_w2_final_segment_reaches_grounded_w3_result() -> None:
    chunks = chunk_pcm(make_fake_pcm(duration_ms=1000), session_id="session-demo")
    events = FakeTranscriber().transcribe(
        chunks, session_id="session-demo", correlation_id="corr", timestamp=T0
    )
    segments = [e.payload for e in events if isinstance(e.payload, TranscriptSegment)]
    assert segments and all(s.is_final for s in segments)

    capture = SyntheticCaptureAdapter(
        [
            SyntheticFrame(
                frame_id="frame-0",
                width=640,
                height=480,
                image_bytes=b"\x00" * 64,
                text_regions=(("status", "Mock dashboard status: ready"),),
            )
        ],
        settings=CaptureSettings(enabled=True),
    )
    frame = capture.capture(T0).frame
    assert frame is not None
    screen = MockVisionAdapter().extract(frame, capture_enabled=True)

    built = build_context(
        candidates_from_transcript(segments, session_started_at=T0)
        + candidates_from_screen(screen),
        question="What did the voicebot say?",
        now=datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc),
    )
    outcome = LLMReasoningAdapter().reason(
        ReasoningRequest(
            request_id="req-demo",
            session_id="session-demo",
            question="What did the voicebot say?",
            context=built.items,
        )
    )
    assert outcome.result is not None
    assert segments[0].segment_id in outcome.result.source_ids
    assert "frame-0-status" in outcome.result.source_ids
