"""Runnable demo for Speech-to-Text (W2) in Academiaai AI Voicebot.

Demonstrates deterministic mock transcription:
1. Generates synthetic 1000ms PCM audio chunks.
2. Transcribes them using FakeTranscriber.
3. Accumulates transcript segments using SegmentAccumulator.
4. Demonstrates interim-to-final replacement and ordering.
"""

from datetime import datetime, timezone

from app.contracts.audio import AudioChunk, AudioFormat
from app.contracts.transcription import TranscriptEvent, TranscriptSegment
from app.transcription.accumulator import SegmentAccumulator
from app.transcription.mock import FakeTranscriber


def run_demo() -> None:
    print("=" * 60)
    print("Academiaai AI Voicebot — Speech-to-Text (W2) Demo")
    print("=" * 60)
    print("Mode: Deterministic Mock (Zero Network, Zero Credentials)")
    print()

    # 1. Initialize transcriber and accumulator
    transcriber = FakeTranscriber(timeout_seconds=5.0)
    accumulator = SegmentAccumulator()
    print(f"Provider health: {transcriber.health()}")

    # 2. Prepare synthetic audio chunks (1000ms = 50 chunks of 20ms)
    session_id = "session-demo"
    correlation_id = "correlation-demo"
    ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    chunks: list[AudioChunk] = []
    chunk_ms = 20
    total_ms = 1000
    for seq, start_ms in enumerate(range(0, total_ms, chunk_ms)):
        pcm_bytes = bytes(chunk_ms * 32)
        chunks.append(
            AudioChunk(
                session_id=session_id,
                sequence_id=seq,
                start_ms=start_ms,
                duration_ms=chunk_ms,
                format=AudioFormat(),
                pcm=pcm_bytes,
            )
        )

    print(
        f"\n1. Generated {len(chunks)} synthetic AudioChunk objects "
        f"({total_ms}ms total)."
    )
    first = chunks[0]
    last = chunks[-1]
    print(
        f"   First chunk: seq={first.sequence_id}, start={first.start_ms}ms, "
        f"dur={first.duration_ms}ms"
    )
    print(
        f"   Last chunk:  seq={last.sequence_id}, start={last.start_ms}ms, "
        f"dur={last.duration_ms}ms"
    )

    # 3. Transcribe using FakeTranscriber
    print("\n2. Transcribing audio chunks with FakeTranscriber...")
    events = transcriber.transcribe(
        chunks,
        session_id=session_id,
        correlation_id=correlation_id,
        timestamp=ts,
    )
    print(f"   Produced {len(events)} TranscriptEvent envelope(s):")
    for event in events:
        print(f"   - Event ID: {event.event_id}")
        print(f"     Type:     {event.event_type} (version {event.schema_version})")
        print(f"     Producer: {event.producer}")
        print(f"     Session:  {event.session_id}")
        print(f"     Payload:  text='{event.payload.text}'")
        print(
            f"               range={event.payload.start_ms}ms..{event.payload.end_ms}ms"
        )
        print(f"               confidence={event.payload.confidence}")
        print(f"               is_final={event.payload.is_final}")

    # 4. Accumulate
    print("\n3. Adding events to SegmentAccumulator...")
    for event in events:
        accumulator.add(event)

    print(f"   Accumulated segments count: {len(accumulator.segments())}")
    print(f'   Accumulated transcript text: "{accumulator.text()}"')

    # 5. Demonstrate Interim-to-Final replacement and ordering
    print("\n4. Demonstrating Interim-to-Final replacement & ordering...")
    interim_seg = TranscriptSegment(
        segment_id="session-demo-segment-1",
        session_id=session_id,
        sequence_id=1,
        start_ms=1000,
        end_ms=1500,
        text="Recognizing speech in progress...",
        confidence=0.85,
        language="en",
        is_final=False,
    )
    interim_event = TranscriptEvent(
        event_id="event-transcript-1-interim",
        event_type="transcript.segment",
        schema_version="1.0",
        session_id=session_id,
        correlation_id=correlation_id,
        timestamp=ts,
        producer="transcription",
        payload=interim_seg,
    )
    accumulator.add(interim_event)
    print(f'   After interim event added: "{accumulator.text()}"')

    final_seg = TranscriptSegment(
        segment_id="session-demo-segment-1",
        session_id=session_id,
        sequence_id=1,
        start_ms=1000,
        end_ms=2000,
        text="Voicebot is ready for interaction.",
        confidence=0.98,
        language="en",
        is_final=True,
    )
    final_event = TranscriptEvent(
        event_id="event-transcript-1-final",
        event_type="transcript.segment",
        schema_version="1.0",
        session_id=session_id,
        correlation_id=correlation_id,
        timestamp=ts,
        producer="transcription",
        payload=final_seg,
    )
    accumulator.add(final_event)
    print(f'   After final replacement:   "{accumulator.text()}"')

    print("\n" + "=" * 60)
    print("Demo completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    run_demo()
