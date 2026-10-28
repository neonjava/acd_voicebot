"""Tests for connected W1 -> W2 -> W5 pipeline."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.contracts.sessions import AudioChunkMetadata, MockSessionResponse
from app.contracts.transcription import TranscriptEvent, TranscriptSegment
from app.sessions.service import MissingDependencyError, SessionService


def test_connected_w1_w2_w5_pipeline_integration():
    """Verify that W5 orchestrates W1 audio and W2 transcriber when present."""
    service = SessionService()
    service.clear()

    # Synthetic 1000ms PCM bytes
    fake_pcm = bytes(32000)
    fake_chunks = [MagicMock() for _ in range(50)]

    fake_segment = TranscriptSegment(
        segment_id="session-connected-segment-0",
        session_id="session-connected",
        sequence_id=0,
        start_ms=0,
        end_ms=1000,
        text="Hello from the connected mock pipeline.",
        confidence=1.0,
        language="en",
        is_final=True,
    )
    fake_transcript_event = TranscriptEvent(
        event_id="event-transcript-connected-0",
        event_type="transcript.segment",
        schema_version="1.0",
        session_id="session-connected",
        correlation_id="corr-connected-1",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        producer="transcription",
        payload=fake_segment,
    )

    mock_transcriber_instance = MagicMock()
    mock_transcriber_instance.transcribe.return_value = [fake_transcript_event]
    mock_transcriber_cls = MagicMock(return_value=mock_transcriber_instance)

    mock_make_pcm = MagicMock(return_value=fake_pcm)
    mock_chunk_pcm = MagicMock(return_value=fake_chunks)

    mock_modules = {
        "app.audio": MagicMock(),
        "app.audio.source": MagicMock(make_fake_pcm=mock_make_pcm),
        "app.audio.chunker": MagicMock(chunk_pcm=mock_chunk_pcm),
        "app.transcription": MagicMock(),
        "app.transcription.mock": MagicMock(FakeTranscriber=mock_transcriber_cls),
    }

    with (
        patch("importlib.util.find_spec", return_value=MagicMock()),
        patch.dict("sys.modules", mock_modules),
    ):
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        response = service.run_mock_session(
            session_id="session-connected",
            correlation_id="corr-connected-1",
            timestamp=ts,
        )

        assert isinstance(response, MockSessionResponse)
        assert response.session_id == "session-connected"
        assert response.state == "completed"
        assert len(response.events) == 2

        # 1. First event is AudioChunkEvent
        audio_event = response.events[0]
        assert audio_event.event_type == "audio.chunk"
        assert audio_event.producer == "audio"
        assert isinstance(audio_event.payload, AudioChunkMetadata)
        assert audio_event.payload.size_bytes == 32000

        # 2. Second event is TranscriptEvent from FakeTranscriber
        trans_event = response.events[1]
        assert trans_event.event_type == "transcript.segment"
        assert trans_event.producer == "transcription"
        assert trans_event.payload.text == "Hello from the connected mock pipeline."

        # Verify calls to W1 and W2 functions
        mock_make_pcm.assert_called_once_with(duration_ms=1000)
        mock_chunk_pcm.assert_called_once_with(
            fake_pcm, session_id="session-connected", chunk_ms=20
        )
        mock_transcriber_instance.transcribe.assert_called_once_with(
            fake_chunks,
            session_id="session-connected",
            correlation_id="corr-connected-1",
            timestamp=ts,
        )


def test_missing_dependencies_raise_blocker_not_silent_fallback():
    """Missing upstream producers raise MissingDependencyError instead of fakes."""
    service = SessionService()
    service.clear()

    with patch("importlib.util.find_spec", return_value=None):
        with pytest.raises(MissingDependencyError) as exc_info:
            service.run_mock_session(session_id="sess-blocker")
        assert "W1" in exc_info.value.dependency_name
