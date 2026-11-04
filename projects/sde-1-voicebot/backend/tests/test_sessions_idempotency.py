"""Tests for idempotent session commands and Idempotency-Key deduplication (W5)."""

import pytest
from fastapi.testclient import TestClient

from app.contracts.common import ErrorEnvelope
from app.main import app
from app.sessions.service import session_service


@pytest.fixture
def client():
    session_service.clear()
    return TestClient(app)


def test_repeated_pause_is_idempotent(client):
    """Calling pause on an already paused session returns 200 without error."""
    created = client.post("/api/sessions", json={"initial_state": "active"}).json()
    sid = created["session_id"]

    # First pause
    resp1 = client.post(f"/api/sessions/{sid}/pause")
    assert resp1.status_code == 200
    assert resp1.json()["state"] == "paused"

    # Second pause (idempotent repeat)
    resp2 = client.post(f"/api/sessions/{sid}/pause")
    assert resp2.status_code == 200
    assert resp2.json()["state"] == "paused"


def test_repeated_resume_is_idempotent(client):
    """Calling resume on an already active session returns 200 without error."""
    created = client.post("/api/sessions", json={"initial_state": "active"}).json()
    sid = created["session_id"]

    resp = client.post(f"/api/sessions/{sid}/resume")
    assert resp.status_code == 200
    assert resp.json()["state"] == "active"


def test_repeated_stop_is_idempotent(client):
    """Calling stop on an already completed session returns 200 without error."""
    created = client.post("/api/sessions", json={"initial_state": "active"}).json()
    sid = created["session_id"]

    resp1 = client.post(f"/api/sessions/{sid}/stop")
    assert resp1.status_code == 200
    assert resp1.json()["state"] == "completed"

    resp2 = client.post(f"/api/sessions/{sid}/stop")
    assert resp2.status_code == 200
    assert resp2.json()["state"] == "completed"


def test_idempotency_key_deduplication_create(client):
    """Requests with identical Idempotency-Key return the cached response."""
    key = "idem-key-unique-12345"
    headers = {"Idempotency-Key": key}

    resp1 = client.post(
        "/api/sessions", json={"initial_state": "created"}, headers=headers
    )
    assert resp1.status_code == 201
    sid1 = resp1.json()["session_id"]

    # Replay same request with same key
    resp2 = client.post(
        "/api/sessions", json={"initial_state": "created"}, headers=headers
    )
    assert resp2.status_code == 201
    sid2 = resp2.json()["session_id"]

    # Must return the identical cached session_id
    assert sid1 == sid2


def test_idempotency_key_deduplication_pause(client):
    """Action commands with Idempotency-Key return cached response."""
    created = client.post("/api/sessions", json={"initial_state": "active"}).json()
    sid = created["session_id"]

    key = "idem-pause-key-777"
    headers = {"Idempotency-Key": key}

    resp1 = client.post(f"/api/sessions/{sid}/pause", headers=headers)
    assert resp1.status_code == 200
    assert resp1.json()["state"] == "paused"

    resp2 = client.post(f"/api/sessions/{sid}/pause", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json() == resp1.json()


def test_invalid_idempotency_key_rejected(client):
    """Invalid Idempotency-Key format returns 422 error envelope."""
    # Key with invalid characters (spaces)
    headers = {"Idempotency-Key": "invalid key with spaces"}
    resp = client.post("/api/sessions", headers=headers)
    assert resp.status_code == 422
    err = ErrorEnvelope.model_validate(resp.json())
    assert err.code in ("HTTP_422", "VALIDATION_ERROR")
