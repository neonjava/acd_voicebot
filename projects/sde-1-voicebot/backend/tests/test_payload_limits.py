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


def test_chunked_oversized_body_rejected(client):
    """Chunked streaming request without Content-Length exceeding limit returns 413."""

    def oversized_chunks():
        chunk = b"a" * 16384
        for _ in range(5):  # 5 * 16384 = 81920 bytes > 65536
            yield chunk

    resp = client.post(
        "/api/sessions",
        content=oversized_chunks(),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 413
    err = ErrorEnvelope.model_validate(resp.json())
    assert err.code == "PAYLOAD_TOO_LARGE"


def test_invalid_content_length_rejected(client):
    """Non-integer Content-Length header returns 400 INVALID_CONTENT_LENGTH."""
    resp = client.post(
        "/api/sessions",
        json={"initial_state": "created"},
        headers={"Content-Length": "invalid-length"},
    )
    assert resp.status_code == 400
    err = ErrorEnvelope.model_validate(resp.json())
    assert err.code == "INVALID_CONTENT_LENGTH"


def test_negative_content_length_rejected(client):
    """Negative Content-Length header returns 400 INVALID_CONTENT_LENGTH."""
    resp = client.post(
        "/api/sessions",
        json={"initial_state": "created"},
        headers={"Content-Length": "-100"},
    )
    assert resp.status_code == 400
    err = ErrorEnvelope.model_validate(resp.json())
    assert err.code == "INVALID_CONTENT_LENGTH"


def test_valid_payload_size_accepted(client):
    """Requests within limits are processed normally."""
    resp = client.post("/api/sessions", json={"initial_state": "created"})
    assert resp.status_code == 201
