"""Reconnect and event replay tests ensuring missed events are replayed without loss."""

import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.contracts.common import SessionState
from app.contracts.sessions import AudioChunkEvent, AudioChunkMetadata
from app.main import app
from app.sessions.service import session_service

client = TestClient(app)


def test_reconnect_replays_missed_events_in_order():
    """Verify that a reconnecting client receives all missed events in order."""
    sess = session_service.create_session(
        "sess-replay-1", initial_state=SessionState.active
    )
    session_id = sess.session_id

    # Add 10 events to the session
    for i in range(10):
        ev = AudioChunkEvent(
            event_id=f"event-{uuid.uuid4().hex[:8]}",
            event_type="audio.chunk",
            schema_version="1.0",
            session_id=session_id,
            correlation_id=f"corr-{i}",
            timestamp=datetime.now(timezone.utc),
            producer="audio",
            payload=AudioChunkMetadata(
                sequence_id=i,
                start_ms=i * 100,
                duration_ms=100,
                sample_rate_hz=16000,
                channels=1,
                size_bytes=3200,
            ),
        )
        session_service.add_event(session_id, ev)

    # 1. Full replay from sequence 0
    resp_all = client.get(f"/api/sessions/{session_id}/events?from_sequence=0&limit=50")
    assert resp_all.status_code == 200
    all_events = resp_all.json()["events"]
    assert len(all_events) == 10

    # 2. Simulate client that was disconnected after sequence 4
    # Reconnecting client asks for missed events starting from sequence 5
    resp_missed = client.get(
        f"/api/sessions/{session_id}/events?from_sequence=5&limit=50"
    )
    assert resp_missed.status_code == 200
    missed_events = resp_missed.json()["events"]
    assert len(missed_events) == 5

    # Check exact continuity and ordering
    for idx, ev in enumerate(missed_events):
        expected_seq = 5 + idx
        assert ev["correlation_id"] == f"corr-{expected_seq}"


def test_reconnect_with_limit_and_pagination():
    """Verify that reconnect pagination works smoothly when event buffer is large."""
    sess = session_service.create_session(
        "sess-replay-page", initial_state=SessionState.active
    )
    session_id = sess.session_id

    for i in range(15):
        ev = AudioChunkEvent(
            event_id=f"event-{uuid.uuid4().hex[:8]}",
            event_type="audio.chunk",
            schema_version="1.0",
            session_id=session_id,
            correlation_id=f"corr-p-{i}",
            timestamp=datetime.now(timezone.utc),
            producer="audio",
            payload=AudioChunkMetadata(
                sequence_id=i,
                start_ms=i * 100,
                duration_ms=100,
                sample_rate_hz=16000,
                channels=1,
                size_bytes=3200,
            ),
        )
        session_service.add_event(session_id, ev)

    # Page 1: from 0, limit 5
    r1 = client.get(f"/api/sessions/{session_id}/events?from_sequence=0&limit=5")
    p1 = r1.json()["events"]
    assert len(p1) == 5
    assert p1[0]["correlation_id"] == "corr-p-0"
    assert p1[-1]["correlation_id"] == "corr-p-4"

    # Page 2: from 5, limit 5
    r2 = client.get(f"/api/sessions/{session_id}/events?from_sequence=5&limit=5")
    p2 = r2.json()["events"]
    assert len(p2) == 5
    assert p2[0]["correlation_id"] == "corr-p-5"
    assert p2[-1]["correlation_id"] == "corr-p-9"

    # Page 3: from 10, limit 10
    p3 = client.get(
        f"/api/sessions/{session_id}/events?from_sequence=10&limit=10"
    ).json()["events"]
    assert len(p3) == 5
    assert p3[0]["correlation_id"] == "corr-p-10"
    assert p3[-1]["correlation_id"] == "corr-p-14"


def test_reconnect_from_sequence_past_end():
    """Requesting sequence beyond available events returns an empty list cleanly."""
    sess = session_service.create_session(
        "sess-replay-empty", initial_state=SessionState.active
    )
    resp = client.get(
        f"/api/sessions/{sess.session_id}/events?from_sequence=100&limit=10"
    )
    assert resp.status_code == 200
    assert resp.json()["events"] == []
