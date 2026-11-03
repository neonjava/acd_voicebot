"""Runnable demo for Speech-to-Text (W2 - Week 2) in Academiaai AI Voicebot.

Demonstrates:
1. Real W1 synthetic audio generation and chunking.
2. Audio preprocessing (deterministic amplitude normalization).
3. End-to-end orchestration with retry policy and timeout boundary.
4. Out-of-order segment arrival and chronological ordering in SegmentAccumulator.
5. Interim-to-final replacement and text revision tracking.
6. Exact duplicate suppression.
7. Simulated transient retry recovery.
8. Handoff of finalized segments to W3 reasoning context item.
"""

from datetime import datetime, timezone

from app.audio.chunker import chunk_pcm
from app.audio.source import make_fake_pcm
from app.contracts.transcription import TranscriptSegment
from app.reasoning.context import context_item_from_transcript
from app.transcription.accumulator import SegmentAccumulator
from app.transcription.mock import FakeTranscriber
from app.transcription.orchestrator import TranscriptionOrchestrator
from app.transcription.preprocessing import AudioPreprocessor, normalize_amplitude
from app.transcription.retry import RetryPolicy


def run_week2_demo() -> None:
    print("=" * 65)
    print("Academiaai AI Voicebot — Speech-to-Text (W2: Week 2) Demo")
    print("=" * 65)
    print("Mode: Deterministic Mock (Zero Network, Zero Credentials)")
    print()

    session_id = "session-w2-demo"
    correlation_id = "corr-w2-demo"
    ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    # 1. Real W1 audio generation
    print("1. Generating 1000ms synthetic PCM via W1 make_fake_pcm...")
    pcm = make_fake_pcm(duration_ms=1000)
    print(f"   Raw PCM bytes: {len(pcm)} (16kHz 16-bit mono)")

    # 2. Preprocessing
    print("\n2. Applying amplitude normalization...")
    normalized_pcm = normalize_amplitude(pcm, target_peak=0.90)
    print(f"   Normalized PCM bytes: {len(normalized_pcm)} (peak target=90%)")

    # 3. Chunking
    chunks = chunk_pcm(normalized_pcm, session_id=session_id, chunk_ms=20)
    print(f"   Created {len(chunks)} AudioChunk objects (20ms each)")

    # 4. Transcription Orchestration
    print("\n3. Running TranscriptionOrchestrator...")
    orchestrator = TranscriptionOrchestrator(
        adapter=FakeTranscriber(),
        preprocessor=AudioPreprocessor(normalize=True, target_peak=0.90),
        retry_policy=RetryPolicy(max_retries=2),
    )
    print(f"   Provider health: {orchestrator.health()}")

    events = orchestrator.process_chunks(
        chunks,
        session_id=session_id,
        correlation_id=correlation_id,
        timestamp=ts,
    )
    print(f"   Emitted {len(events)} TranscriptEvent envelope(s)")
    for evt in events:
        if evt.event_type == "transcript.segment" and isinstance(
            evt.payload, TranscriptSegment
        ):
            print(
                f"   - Segment ID: {evt.payload.segment_id} | "
                f"Text: '{evt.payload.text}' | "
                f"Range: {evt.payload.start_ms}ms..{evt.payload.end_ms}ms"
            )

    # 5. Out-of-order & Revision demonstration in Accumulator
    print("\n4. Demonstrating Accumulator out-of-order arrivals & revision tracking...")
    acc = SegmentAccumulator()

    # Arriving out-of-order: Segment 2 (start=2000ms) arrives first!
    seg_2 = TranscriptSegment(
        segment_id="seg-2",
        session_id=session_id,
        sequence_id=2,
        start_ms=2000,
        end_ms=3000,
        text="World",
        is_final=True,
    )
    acc.add(seg_2)

    # Segment 1 arrives as interim (start=0ms)
    seg_1_interim = TranscriptSegment(
        segment_id="seg-1",
        session_id=session_id,
        sequence_id=0,
        start_ms=0,
        end_ms=1000,
        text="Helo",
        is_final=False,
    )
    acc.add(seg_1_interim)
    print(f'   Text after out-of-order interim: "{acc.text()}"')

    # Segment 1 revised interim: text typo fixed
    seg_1_revised = TranscriptSegment(
        segment_id="seg-1",
        session_id=session_id,
        sequence_id=1,
        start_ms=0,
        end_ms=1000,
        text="Hello",
        is_final=False,
    )
    acc.add(seg_1_revised)
    print(
        f'   Text after interim revision:     "{acc.text()}" '
        f"(seg-1 revisions: {acc.revisions_count('seg-1')})"
    )

    # Segment 1 finalized
    seg_1_final = TranscriptSegment(
        segment_id="seg-1",
        session_id=session_id,
        sequence_id=2,
        start_ms=0,
        end_ms=1000,
        text="Hello",
        is_final=True,
    )
    acc.add(seg_1_final)
    print(f'   Text after finalization:         "{acc.text()}"')

    # Duplicate final arrival
    added_duplicate = acc.add(seg_1_final)
    print(f"   Adding duplicate final segment:  handled={added_duplicate} (ignored)")
    print(f'   Combined text unchanged:         "{acc.text()}"')

    # 6. Retry recovery demonstration
    print("\n5. Demonstrating Bounded Retry Policy with simulated transient failure...")
    transient_transcriber = FakeTranscriber(failures_before_success=1)
    retry_orchestrator = TranscriptionOrchestrator(
        adapter=transient_transcriber,
        retry_policy=RetryPolicy(max_retries=2),
    )
    retry_events = retry_orchestrator.process_chunks(
        chunks[:5],
        session_id=session_id,
        correlation_id=correlation_id,
        timestamp=ts,
    )
    print(
        f"   Transient failure successfully retried! Emitted event: "
        f"{retry_events[0].event_type} (text='{retry_events[0].payload.text}')"
    )

    # 7. W3 reasoning handoff
    print("\n6. Demonstrating handoff of finalized segment to W3 Reasoning...")
    final_segments = acc.final_segments()
    context_item = context_item_from_transcript(final_segments[0])
    print(
        f"   Created ContextItem: id='{context_item.item_id}', "
        f"kind='{context_item.source.kind}', text='{context_item.text}'"
    )

    print("\n" + "=" * 65)
    print("Week 2 Speech-to-Text demo completed successfully!")
    print("=" * 65)


if __name__ == "__main__":
    run_week2_demo()
