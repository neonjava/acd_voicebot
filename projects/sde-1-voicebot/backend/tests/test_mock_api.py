"""Route tests for POST /api/sessions/mock and fixture validation."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.contracts.sessions import MockSessionResponse
from app.main import app
from app.sessions.service import session_service


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


def test_post_mock_session_generates_unique_session_ids(client):
    """Subsequent POST requests must generate distinct session IDs in memory."""
    resp1 = client.post("/api/sessions/mock", json={})
    resp2 = client.post("/api/sessions/mock", json={})

    assert resp1.status_code == 201
    assert resp2.status_code == 201

    sid1 = resp1.json()["session_id"]
    sid2 = resp2.json()["session_id"]

    assert sid1 != sid2, "Session IDs must be unique across runtime requests"
    assert session_service.get_session(sid1) is not None
    assert session_service.get_session(sid2) is not None


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
    assert data["details_redacted"]["body"] == "Unexpected extra field in payload."


def test_validation_error_does_not_echo_secret_keys(client):
    """User-supplied key names or sensitive data must never leak in error details."""
    secret_key = "secret-token-in-key"
    secret_val = "sensitive-credential-value"
    response = client.post(
        "/api/sessions/mock",
        json={secret_key: secret_val},
    )
    assert response.status_code == 422
    assert secret_key not in response.text
    assert secret_val not in response.text
    assert (
        response.json()["details_redacted"]["body"]
        == "Unexpected extra field in payload."
    )


def test_session_fixture_matches_contract():
    """Verify that session_response.json is valid against MockSessionResponse."""
    fixture_path = Path(__file__).parent / "fixtures" / "session_response.json"
    assert fixture_path.exists(), "session_response.json fixture must exist"

    with open(fixture_path, "r", encoding="utf-8") as f:
        content = json.load(f)

    validated = MockSessionResponse.model_validate(content)
    assert validated.session_id == "session-demo"
    assert validated.state == "completed"
    assert validated.mode == "mock"
    assert len(validated.events) == 2
    assert validated.events[0].event_type == "audio.chunk"
    assert validated.events[1].event_type == "transcript.segment"


def test_fixture_matches_service_output():
    """Verify fixture directly matches service output for baseline demo params."""
    fixture_path = Path(__file__).parent / "fixtures" / "session_response.json"
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))

    baseline_ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    actual_model = session_service.run_mock_session(
        session_id="session-demo",
        correlation_id="correlation-demo",
        timestamp=baseline_ts,
    )
    actual = actual_model.model_dump(mode="json")
    assert actual == expected, "Fixture must not drift from service output"
