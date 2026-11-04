"""Tests for ordered session event streaming and replay endpoints (W5)."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.contracts.common import ErrorEnvelope
from app.contracts.sessions import (
    AudioChunkEvent,
    AudioChunkMetadata,
    SessionEventStreamResponse,
)
from app.contracts.transcription import TranscriptEvent, TranscriptSegment
from app.main import app
from app.sessions.service import session_service


@pytest.fixture
def client():
    session_service.clear()
    return TestClient(app)


def test_get_session_events_replay(client):
    """GET /api/sessions/{id}/events returns ordered events with pagination."""
    # Create active session and add events
    sid = "sess-events-1"
    session_service.create_session(sid, initial_state="active")

    ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        audio_evt = AudioChunkEvent(
            event_id=f"evt-audio-{i}",
            event_type="audio.chunk",
            schema_version="1.0",
            session_id=sid,
            correlation_id="corr-test",
            timestamp=ts,
            producer="audio",
            payload=AudioChunkMetadata(
                sequence_id=i,
                start_ms=i * 20,
                duration_ms=20,
                sample_rate_hz=16000,
                channels=1,
                size_bytes=640,
            ),
        )
        session_service.add_event(sid, audio_evt)

    # Fetch all from sequence 0
    resp = client.get(f"/api/sessions/{sid}/events?from_sequence=0&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    model = SessionEventStreamResponse.model_validate(data)
    assert model.session_id == sid
    assert len(model.events) == 5
    assert model.total_events == 5

    # Fetch from sequence 3
    resp_slice = client.get(f"/api/sessions/{sid}/events?from_sequence=3&limit=2")
    assert resp_slice.status_code == 200
    model_slice = SessionEventStreamResponse.model_validate(resp_slice.json())
    assert len(model_slice.events) == 2
    assert model_slice.events[0].payload.sequence_id == 3
    assert model_slice.events[1].payload.sequence_id == 4


def test_stream_session_events_sse(client):
    """GET /api/sessions/{id}/events/stream returns text/event-stream SSE output."""
    sid = "sess-stream-1"
    session_service.create_session(sid, initial_state="active")

    ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    trans_evt = TranscriptEvent(
        event_id="evt-tr-1",
        event_type="transcript.segment",
        schema_version="1.0",
        session_id=sid,
        correlation_id="corr-stream",
        timestamp=ts,
        producer="transcription",
        payload=TranscriptSegment(
            segment_id="seg-1",
            session_id=sid,
            sequence_id=0,
            start_ms=0,
            end_ms=1000,
            text="Streaming test segment",
            confidence=1.0,
            language="en",
            is_final=True,
        ),
    )
    session_service.add_event(sid, trans_evt)

    resp = client.get(f"/api/sessions/{sid}/events/stream")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    text = resp.text
    assert "event: session.event" in text
    assert "Streaming test segment" in text
    assert "event: session.status" in text


def test_events_nonexistent_session_returns_404(client):
    """Querying events for unknown session returns 404 SESSION_NOT_FOUND."""
    resp = client.get("/api/sessions/sess-unknown/events")
    assert resp.status_code == 404
    err = ErrorEnvelope.model_validate(resp.json())
    assert err.code == "SESSION_NOT_FOUND"
