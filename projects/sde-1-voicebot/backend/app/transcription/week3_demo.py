"""Week 3 Speech-to-Text demo: speech events, revisions, confidence, and fallback."""

from datetime import datetime, timezone

from app.audio.chunker import chunk_pcm
from app.audio.source import make_fake_pcm
from app.contracts.audio import SpeechEvent
from app.contracts.transcription import TranscriptEvent
from app.transcription.accumulator import SegmentAccumulator
from app.transcription.config import TranscriptionConfig
from app.transcription.faster_whisper import FasterWhisperAdapter
from app.transcription.mock import FakeTranscriber
from app.transcription.orchestrator import TranscriptionOrchestrator


def run_week3_demo() -> None:
    print("=" * 65)
    print("Academiaai AI Voicebot - Speech-to-Text (W2: Week 3) Demo")
    print("=" * 65)
    print("Mode: Deterministic Mock / Real Provider with Fallback\n")

    session_id = "session-w3-demo"
    corr_id = "corr-w3-demo"
    ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    # 1. Simulate W1 Audio & SpeechEvent stream
    print("1. Consuming W1 SpeechEvent boundaries and raw AudioChunks...")
    raw_pcm = make_fake_pcm(duration_ms=1000)
    chunks = chunk_pcm(raw_pcm, session_id=session_id, chunk_ms=20)
    print(f"   Generated {len(chunks)} audio chunks (20ms each, 16kHz mono).")

    speech_events = [
        SpeechEvent(
            kind="wake",
            session_id=session_id,
            correlation_id=corr_id,
            sequence_id=0,
            at_ms=0,
            wake_word="hey_jarvis",
            score=0.98,
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
            at_ms=800,
        ),
    ]
    print(
        "   Received SpeechEvents: wake (0ms) -> speech_start (100ms) -> "
        "speech_end (800ms)"
    )

    # Stream sink for W5 event stream integration
    stream_events: list[TranscriptEvent] = []

    def mock_event_sink(_sid: str, event: TranscriptEvent) -> None:
        stream_events.append(event)

    orchestrator = TranscriptionOrchestrator(
        adapter=FakeTranscriber(),
        event_sink=mock_event_sink,
    )

    evts = orchestrator.process_speech_session(
        speech_events,
        chunks,
        session_id=session_id,
        correlation_id=corr_id,
        timestamp=ts,
    )
    print(f"   Transcribed bounded utterance -> {len(evts)} segment event(s).")
    seg = evts[0].payload
    print(
        f"   Segment: text='{seg.text}' | start={seg.start_ms}ms | "
        f"end={seg.end_ms}ms | is_final={seg.is_final}"
    )

    # 2. Revisions and Finalization
    print("\n2. Demonstrating Interim Revisions and Finalization...")
    acc = SegmentAccumulator(confidence_threshold=0.4)
    from app.contracts.transcription import TranscriptSegment

    s_v1 = TranscriptSegment(
        segment_id="seg-rev-1",
        session_id=session_id,
        sequence_id=0,
        start_ms=0,
        end_ms=500,
        text="Open the",
        confidence=0.8,
        is_final=False,
    )
    acc.add(s_v1)
    print(
        f"   Interim 1: '{acc.text()}' (revisions: {acc.revisions_count('seg-rev-1')})"
    )

    s_v2 = TranscriptSegment(
        segment_id="seg-rev-1",
        session_id=session_id,
        sequence_id=1,
        start_ms=0,
        end_ms=800,
        text="Open the browser",
        confidence=0.85,
        is_final=False,
    )
    acc.add(s_v2)
    print(
        f"   Interim 2: '{acc.text()}' (revisions: {acc.revisions_count('seg-rev-1')})"
    )

    s_final = TranscriptSegment(
        segment_id="seg-rev-1",
        session_id=session_id,
        sequence_id=2,
        start_ms=0,
        end_ms=1000,
        text="Open the browser.",
        confidence=0.95,
        is_final=True,
    )
    acc.add(s_final)
    print(
        f"   Finalized: '{acc.text()}' "
        f"(revisions: {acc.revisions_count('seg-rev-1')}, "
        f"final_segments: {len(acc.final_segments())})"
    )

    # 3. Confidence Threshold Handling
    print("\n3. Demonstrating Configurable Confidence Threshold (default 0.4)...")
    s_low = TranscriptSegment(
        segment_id="seg-low-1",
        session_id=session_id,
        sequence_id=3,
        start_ms=1000,
        end_ms=1500,
        text="[mumble]",
        confidence=0.25,
        is_final=True,
    )
    acc.add(s_low)
    print(
        "   Added low-confidence segment (confidence=0.25 < threshold 0.4): "
        f"'{s_low.text}'"
    )
    print(
        f"   Final text (without low_confidence flag): "
        f"'{acc.final_text(include_low_confidence=False)}'"
    )
    print(
        f"   Final text (with low_confidence flag):    "
        f"'{acc.final_text(include_low_confidence=True)}'"
    )

    # 4. Fallback to Mock Provider
    print("\n4. Demonstrating FasterWhisperAdapter automatic fallback to Mock...")
    fw_adapter = FasterWhisperAdapter(
        config=TranscriptionConfig(provider="faster_whisper", fallback_to_mock=True)
    )
    fw_events = fw_adapter.transcribe(
        chunks[:5],
        session_id=session_id,
        correlation_id=corr_id,
        timestamp=ts,
    )
    print(f"   Emitted {len(fw_events)} events during fallback:")
    for e in fw_events:
        if e.event_type == "transcript.error":
            print(
                f"   - ErrorEvent: code='{e.payload.code}' | "
                f"message='{e.payload.message_safe_for_user}'"
            )
        else:
            print(f"   - SegmentEvent: text='{e.payload.text}'")

    # 5. Event Stream Integration
    print("\n5. Verifying W5 Session Event Stream Integration...")
    print(f"   Total events published to session event sink: {len(stream_events)}")
    for e in stream_events:
        print(f"   - Streamed {e.event_type} (session_id={e.session_id})")

    print("\n" + "=" * 65)
    print("Week 3 Speech-to-Text demo completed successfully!")
    print("=" * 65)


if __name__ == "__main__":
    run_week3_demo()
