"""Connected W1 -> W2 integration test: audio chunks to transcripts."""

from datetime import datetime, timezone

from app.audio.chunker import chunk_pcm
from app.audio.source import make_fake_pcm
from app.transcription.accumulator import SegmentAccumulator
from app.transcription.mock import FakeTranscriber


def test_connected_audio_to_transcript_pipeline() -> None:
    """Verify real W1 make_fake_pcm and chunk_pcm feed into FakeTranscriber."""
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
    assert len(acc.segments()) == 1
