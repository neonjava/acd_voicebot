"""Tests for event history, replay with from_sequence, and SSE reconnect."""

from fastapi.testclient import TestClient

from app.main import app
from app.sessions.service import session_service


def test_ordered_event_history_replay_with_from_sequence():
    """Client gets ordered slice with no gaps or duplicates from offset."""
    session_service.clear()
    record, events = session_service.run_pipeline_session(
        session_id="sess-replay-test",
        correlation_id="corr-replay-test",
        auto_approve=True,
    )
    total = len(events)
    assert total >= 4

    client = TestClient(app)

    # Fetch with from_sequence=0
    res0 = client.get("/api/sessions/sess-replay-test/events?from_sequence=0&limit=100")
    assert res0.status_code == 200
    data0 = res0.json()
    assert data0["total_events"] == total
    assert len(data0["events"]) == total
    assert data0["has_more"] is False

    # Fetch second half starting from offset 2
    offset = 2
    res_offset = client.get(
        f"/api/sessions/sess-replay-test/events?from_sequence={offset}&limit=100"
    )
    assert res_offset.status_code == 200
    data_offset = res_offset.json()
    assert data_offset["from_sequence"] == offset
    assert len(data_offset["events"]) == total - offset

    # Ensure events match exactly with no duplication or missing items
    for i in range(len(data_offset["events"])):
        assert (
            data_offset["events"][i]["event_id"]
            == data0["events"][offset + i]["event_id"]
        )


def test_reconnect_stream_replays_from_offset_then_follows():
    """SSE event stream replays from offset without gaps then finishes."""
    session_service.clear()
    session_service.run_pipeline_session(
        session_id="sess-sse-reconnect",
        correlation_id="corr-sse-reconnect",
        auto_approve=True,
    )
    client = TestClient(app)

    # Connect to stream with from_sequence=1
    res = client.get("/api/sessions/sess-sse-reconnect/events/stream?from_sequence=1")
    assert res.status_code == 200
    content = res.text

    assert "event: session.event" in content
    assert "event: session.status" in content
    assert '"state": "completed"' in content
