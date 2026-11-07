"""W3 Week 2 demo: opt-in capture, mock OCR, bounded context and LLM adapter.

Everything is synthetic: no screen, model, network or API key is used.
"""

from datetime import datetime, timedelta, timezone

from app.contracts.reasoning import CaptureSettings, ReasoningRequest
from app.contracts.transcription import TranscriptSegment
from app.reasoning.capture import SyntheticCaptureAdapter, SyntheticFrame
from app.reasoning.context_builder import (
    build_context,
    candidates_from_screen,
    candidates_from_transcript,
)
from app.reasoning.llm import LLMReasoningAdapter, MockLLMProvider
from app.reasoning.vision import MockVisionAdapter

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def main() -> None:
    frames = [
        SyntheticFrame(
            frame_id="frame-0",
            width=1280,
            height=720,
            image_bytes=b"\x00" * 256,
            text_regions=(
                ("title", "Course dashboard"),
                ("status", "Assignment status: submitted"),
            ),
        ),
        SyntheticFrame(
            frame_id="frame-big",
            width=4000,
            height=3000,
            image_bytes=b"\x00" * 256,
            text_regions=(("x", "too large"),),
        ),
    ]
    capture = SyntheticCaptureAdapter(
        frames, settings=CaptureSettings(sampling_interval_ms=1000)
    )
    print("1. Opt-in capture (synthetic frames only)")
    print(f"   before opt-in: {capture.capture(T0).status}")
    capture.enable()
    first = capture.capture(T0)
    print(f"   after opt-in: {first.status}")
    print(f"   0.5 s later: {capture.capture(T0 + timedelta(milliseconds=500)).status}")
    big = capture.capture(T0 + timedelta(seconds=1))
    print(f"   oversized frame: {big.status} ({big.error.code if big.error else '-'})")

    assert first.frame is not None
    screen = MockVisionAdapter().extract(first.frame, capture_enabled=True)
    print(f"2. Mock OCR items: {[item.item_id for item in screen.items]}")

    segment = TranscriptSegment(
        segment_id="session-demo-segment-0",
        session_id="session-demo",
        sequence_id=0,
        start_ms=0,
        end_ms=1000,
        text="Hello from the mock voicebot.",
    )
    question = "What is the assignment status?"
    built = build_context(
        candidates_from_screen(screen)
        + candidates_from_transcript([segment], session_started_at=T0),
        question=question,
        now=T0 + timedelta(seconds=2),
        token_budget=16,
    )
    print("3. Context builder (budget 16 approx. tokens)")
    print(f"   chosen={[item.item_id for item in built.items]}")
    print(f"   used_tokens={built.used_tokens} dropped={built.dropped_over_budget}")

    request = ReasoningRequest(
        request_id="reasoning-week2-demo",
        session_id="session-demo",
        question=question,
        context=built.items,
    )
    print("4. LLM adapter (mock provider)")
    ok = LLMReasoningAdapter().reason(request)
    assert ok.result is not None
    print(f"   result source_ids={ok.result.source_ids} attempts={ok.attempts}")
    retried = LLMReasoningAdapter(MockLLMProvider(["timeout"])).reason(request)
    print(f"   one timeout then success: attempts={retried.attempts}")
    bad = LLMReasoningAdapter(MockLLMProvider(["not json"])).reason(request)
    print(f"   malformed output: {bad.error.code if bad.error else '-'}")


if __name__ == "__main__":
    main()
