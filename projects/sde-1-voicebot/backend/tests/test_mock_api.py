"""Route tests for POST /api/sessions/mock and fixture validation."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.contracts.sessions import MockSessionResponse
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_post_mock_session_success(client):
    """POST /api/sessions/mock with empty body returns 201 MockSessionResponse."""
    response = client.post(
        "/api/sessions/mock",
        json={},
        headers={"X-Correlation-ID": "test-corr-abc"},
    )
    assert response.status_code == 201
    assert response.headers["X-Correlation-ID"] == "test-corr-abc"
    assert "X-Request-ID" in response.headers

    data = response.json()
    validated = MockSessionResponse.model_validate(data)
    assert validated.state == "completed"
    assert validated.mode == "mock"
    assert len(validated.events) == 2
    assert validated.events[0].event_type == "audio.chunk"
    assert validated.events[1].event_type == "transcript.segment"


def test_post_mock_session_rejects_extra_fields(client):
    """POST /api/sessions/mock with unexpected payload returns 422 ErrorEnvelope."""
    response = client.post(
        "/api/sessions/mock",
        json={"unexpected_field": "disallowed"},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "VALIDATION_ERROR"
    assert data["retryable"] is False
    assert "correlation_id" in data
    assert "body.unexpected_field" in data[
        "details_redacted"
    ] or "unexpected_field" in str(data["details_redacted"])


def test_session_fixture_matches_contract():
    """Verify that session_response.json is valid against MockSessionResponse."""
    fixture_path = Path(__file__).parent / "fixtures" / "session_response.json"
    assert fixture_path.exists(), "session_response.json fixture must exist"

    with open(fixture_path, "r", encoding="utf-8") as f:
        content = json.load(f)

    # Validate against Pydantic model
    validated = MockSessionResponse.model_validate(content)
    assert validated.session_id == "session-demo"
    assert validated.state == "completed"
    assert validated.mode == "mock"
    assert len(validated.events) == 2
    assert validated.events[0].event_type == "audio.chunk"
    assert validated.events[1].event_type == "transcript.segment"
