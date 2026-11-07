"""Tests for ordered session event streaming and replay endpoints (W5)."""

import threading
import time
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
    assert model.has_more is False

    # Fetch from sequence 3
    resp_slice = client.get(f"/api/sessions/{sid}/events?from_sequence=3&limit=2")
    assert resp_slice.status_code == 200
    model_slice = SessionEventStreamResponse.model_validate(resp_slice.json())
    assert len(model_slice.events) == 2
    assert model_slice.events[0].payload.sequence_id == 3
    assert model_slice.events[1].payload.sequence_id == 4
    assert model_slice.has_more is False


def test_event_cursor_mixed_producers_paging_one_by_one(client):
    """Event cursor handles multiple producers with sequence_id 0 without loss."""
    sid = "sess-mixed-cursor"
    session_service.create_session(sid, initial_state="active")

    ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    # Both audio and transcript have payload sequence_id = 0
    audio_evt = AudioChunkEvent(
        event_id="evt-audio-0",
        event_type="audio.chunk",
        schema_version="1.0",
        session_id=sid,
        correlation_id="corr-mixed",
        timestamp=ts,
        producer="audio",
        payload=AudioChunkMetadata(
            sequence_id=0,
            start_ms=0,
            duration_ms=20,
            sample_rate_hz=16000,
            channels=1,
            size_bytes=640,
        ),
    )
    transcript_evt = TranscriptEvent(
        event_id="evt-transcript-0",
        event_type="transcript.segment",
        schema_version="1.0",
        session_id=sid,
        correlation_id="corr-mixed",
        timestamp=ts,
        producer="transcription",
        payload=TranscriptSegment(
            segment_id=f"{sid}-seg-0",
            session_id=sid,
            sequence_id=0,
            start_ms=0,
            end_ms=1000,
            text="First transcript segment.",
            is_final=True,
        ),
    )
    session_service.add_event(sid, audio_evt)
    session_service.add_event(sid, transcript_evt)

    # Page 1: from_sequence=0, limit=1
    page1 = client.get(f"/api/sessions/{sid}/events?from_sequence=0&limit=1").json()
    assert len(page1["events"]) == 1
    assert page1["events"][0]["event_type"] == "audio.chunk"
    assert page1["has_more"] is True

    # Page 2: from_sequence=1, limit=1
    page2 = client.get(f"/api/sessions/{sid}/events?from_sequence=1&limit=1").json()
    assert len(page2["events"]) == 1
    assert page2["events"][0]["event_type"] == "transcript.segment"
    assert page2["has_more"] is False

    # Page 3: from_sequence=2, limit=1
    page3 = client.get(f"/api/sessions/{sid}/events?from_sequence=2&limit=1").json()
    assert len(page3["events"]) == 0
    assert page3["has_more"] is False


def test_stream_session_events_sse(client):
    """GET /api/sessions/{id}/events/stream streams events to terminal state."""
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

    # Transition session to completed so SSE finishes cleanly
    session_service.stop_session(sid)

    resp = client.get(f"/api/sessions/{sid}/events/stream")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    text = resp.text
    assert "event: session.event" in text
    assert "Streaming test segment" in text
    assert "event: session.status" in text
    assert '"state": "completed"' in text


def test_stream_session_events_live_delivery(client):
    """SSE delivers events added while stream is open until session completes."""
    sid = "sess-stream-live"
    session_service.create_session(sid, initial_state="active")

    def producer():
        time.sleep(0.1)
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        evt = TranscriptEvent(
            event_id="evt-live-1",
            event_type="transcript.segment",
            schema_version="1.0",
            session_id=sid,
            correlation_id="corr-live",
            timestamp=ts,
            producer="transcription",
            payload=TranscriptSegment(
                segment_id="seg-live-1",
                session_id=sid,
                sequence_id=0,
                start_ms=0,
                end_ms=500,
                text="Live delivered text",
                is_final=True,
            ),
        )
        session_service.add_event(sid, evt)
        time.sleep(0.1)
        session_service.stop_session(sid)

    t = threading.Thread(target=producer)
    t.start()

    resp = client.get(f"/api/sessions/{sid}/events/stream")
    t.join()

    assert resp.status_code == 200
    assert "Live delivered text" in resp.text
    assert "event: session.status" in resp.text


def test_events_nonexistent_session_returns_404(client):
    """Querying events for unknown session returns 404 SESSION_NOT_FOUND."""
    resp = client.get("/api/sessions/sess-unknown/events")
    assert resp.status_code == 404
    err = ErrorEnvelope.model_validate(resp.json())
    assert err.code == "SESSION_NOT_FOUND"
