"""Tests for payload size limits and bounded request validation (W5)."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.contracts.common import ErrorEnvelope
from app.main import app
from app.sessions.service import session_service


@pytest.fixture
def client():
    session_service.clear()
    return TestClient(app)


def test_oversized_content_length_rejected(client):
    """Requests indicating Content-Length greater than max_payload_bytes return 413."""
    oversized = settings.max_payload_bytes + 1000
    headers = {"Content-Length": str(oversized)}

    resp = client.post(
        "/api/sessions", json={"initial_state": "created"}, headers=headers
    )
    assert resp.status_code == 413
    err = ErrorEnvelope.model_validate(resp.json())
    assert err.code == "PAYLOAD_TOO_LARGE"
    assert err.retryable is False
    assert "limit_bytes" in err.details_redacted


def test_valid_payload_size_accepted(client):
    """Requests within limits are processed normally."""
    resp = client.post("/api/sessions", json={"initial_state": "created"})
    assert resp.status_code == 201
