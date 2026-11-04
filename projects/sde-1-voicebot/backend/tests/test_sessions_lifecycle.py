"""API tests for full session lifecycle: create, pause, resume, stop, expiry (W5)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.contracts.common import ErrorEnvelope
from app.contracts.sessions import SessionStateResponse
from app.main import app
from app.sessions.service import session_service


@pytest.fixture
def client():
    session_service.clear()
    return TestClient(app)


def test_create_session_endpoint(client):
    """POST /api/sessions creates a session with created state."""
    response = client.post("/api/sessions", json={"initial_state": "created"})
    assert response.status_code == 201
    data = response.json()
    model = SessionStateResponse.model_validate(data)
    assert model.state == "created"
    assert model.mode == "mock"
    assert model.expires_at is not None


def test_create_session_active_state(client):
    """POST /api/sessions with initial_state=active starts in active state."""
    response = client.post("/api/sessions", json={"initial_state": "active"})
    assert response.status_code == 201
    data = response.json()
    model = SessionStateResponse.model_validate(data)
    assert model.state == "active"


def test_get_session_endpoint(client):
    """GET /api/sessions/{session_id} returns the current session state."""
    created = client.post("/api/sessions", json={"initial_state": "active"}).json()
    sid = created["session_id"]

    response = client.get(f"/api/sessions/{sid}")
    assert response.status_code == 200
    model = SessionStateResponse.model_validate(response.json())
    assert model.session_id == sid
    assert model.state == "active"


def test_pause_and_resume_lifecycle(client):
    """Verify pause (active -> paused) and resume (paused -> active) transitions."""
    created = client.post("/api/sessions", json={"initial_state": "active"}).json()
    sid = created["session_id"]

    # Pause
    pause_resp = client.post(f"/api/sessions/{sid}/pause")
    assert pause_resp.status_code == 200
    assert pause_resp.json()["state"] == "paused"

    # Resume
    resume_resp = client.post(f"/api/sessions/{sid}/resume")
    assert resume_resp.status_code == 200
    assert resume_resp.json()["state"] == "active"


def test_stop_session_lifecycle(client):
    """POST /api/sessions/{session_id}/stop marks session completed."""
    created = client.post("/api/sessions", json={"initial_state": "active"}).json()
    sid = created["session_id"]

    stop_resp = client.post(f"/api/sessions/{sid}/stop")
    assert stop_resp.status_code == 200
    assert stop_resp.json()["state"] == "completed"

    # Completed session is terminal; cannot resume or pause
    pause_after_stop = client.post(f"/api/sessions/{sid}/pause")
    assert pause_after_stop.status_code == 409
    err = ErrorEnvelope.model_validate(pause_after_stop.json())
    assert err.code == "INVALID_STATE_TRANSITION"


def test_illegal_transition_returns_409(client):
    """Attempting illegal transition returns 409 INVALID_STATE_TRANSITION."""
    # Pausing a session that is only in 'created' state is illegal
    created = client.post("/api/sessions", json={"initial_state": "created"}).json()
    sid = created["session_id"]

    resp = client.post(f"/api/sessions/{sid}/pause")
    assert resp.status_code == 409
    err = ErrorEnvelope.model_validate(resp.json())
    assert err.code == "INVALID_STATE_TRANSITION"
    assert err.details_redacted["from_state"] == "created"
    assert err.details_redacted["to_state"] == "paused"


def test_nonexistent_session_returns_404(client):
    """Operations on nonexistent session return 404 SESSION_NOT_FOUND."""
    resp = client.get("/api/sessions/session-nonexistent-123")
    assert resp.status_code == 404
    err = ErrorEnvelope.model_validate(resp.json())
    assert err.code == "SESSION_NOT_FOUND"


def test_explicit_expire_session(client):
    """POST /api/sessions/{session_id}/expire sets state to expired."""
    created = client.post("/api/sessions", json={"initial_state": "active"}).json()
    sid = created["session_id"]

    exp_resp = client.post(f"/api/sessions/{sid}/expire")
    assert exp_resp.status_code == 200
    assert exp_resp.json()["state"] == "expired"

    # Action on expired session returns 410 SESSION_EXPIRED
    resume_resp = client.post(f"/api/sessions/{sid}/resume")
    assert resume_resp.status_code == 410
    err = ErrorEnvelope.model_validate(resume_resp.json())
    assert err.code == "SESSION_EXPIRED"


def test_automatic_ttl_expiry(client):
    """Session past TTL automatically transitions to expired on access."""
    now = datetime.now(timezone.utc)
    # Create session with 10 second TTL
    record = session_service.create_session("sess-ttl", now=now, ttl_seconds=10)
    assert record.state == "created"

    # Access after 15 seconds
    future_time = now + timedelta(seconds=15)
    expired_record = session_service.get_session("sess-ttl", now=future_time)
    assert expired_record is not None
    assert expired_record.state == "expired"
