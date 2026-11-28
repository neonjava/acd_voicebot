"""Malformed request and error envelope compliance tests."""

from fastapi.testclient import TestClient

from app.contracts.common import ErrorEnvelope, SessionState
from app.main import app
from app.sessions.service import session_service

client = TestClient(app)


def test_malformed_json_body_returns_typed_error_envelope():
    """Sending unparseable JSON returns typed ErrorEnvelope, not 500 or stack trace."""
    sess = session_service.create_session(
        "sess-malformed-1", initial_state=SessionState.active
    )

    endpoints = [
        f"/api/sessions/{sess.session_id}/turns",
        f"/api/sessions/{sess.session_id}/approvals/appr-123",
        f"/api/sessions/{sess.session_id}/listen",
        "/api/sessions",
    ]

    for ep in endpoints:
        resp = client.post(
            ep,
            content=b"this is completely invalid json {{{}}",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code in (400, 422), f"Failed for endpoint: {ep}"
        data = resp.json()
        envelope = ErrorEnvelope.model_validate(data)
        assert envelope.code in ("MALFORMED_REQUEST", "VALIDATION_ERROR")
        assert envelope.message_safe_for_user
        assert envelope.correlation_id is not None
        # Stack traces should never be in response
        assert "traceback" not in resp.text.lower()
        assert 'file "' not in resp.text.lower()


def test_missing_required_fields_returns_typed_error_envelope():
    """Missing required schema fields returns 422 with typed ErrorEnvelope."""
    sess = session_service.create_session(
        "sess-malformed-2", initial_state=SessionState.active
    )

    # Empty turn request (missing required text)
    resp = client.post(f"/api/sessions/{sess.session_id}/turns", json={})
    assert resp.status_code == 422
    env = ErrorEnvelope.model_validate(resp.json())
    assert env.code == "VALIDATION_ERROR"
    assert env.message_safe_for_user

    # Approval decision missing 'decision' field
    resp2 = client.post(
        f"/api/sessions/{sess.session_id}/approvals/appr-123",
        json={"something_else": True},
    )
    assert resp2.status_code == 422
    env2 = ErrorEnvelope.model_validate(resp2.json())
    assert env2.code == "VALIDATION_ERROR"


def test_invalid_field_types_return_typed_error_envelope():
    """Supplying invalid field types (e.g. array) returns typed ErrorEnvelope."""
    sess = session_service.create_session(
        "sess-malformed-3", initial_state=SessionState.active
    )

    resp = client.post(
        f"/api/sessions/{sess.session_id}/turns",
        json={"text": ["not", "a", "string"]},
    )
    assert resp.status_code == 422
    env = ErrorEnvelope.model_validate(resp.json())
    assert env.code == "VALIDATION_ERROR"


def test_nonexistent_session_returns_404_error_envelope():
    """Non-existent session returns 404 with typed ErrorEnvelope."""
    resp = client.get("/api/sessions/non-existent-sess-id")
    assert resp.status_code == 404
    env = ErrorEnvelope.model_validate(resp.json())
    assert env.code == "SESSION_NOT_FOUND"


def test_query_params_validation():
    """Invalid query parameter types return typed ErrorEnvelope."""
    sess = session_service.create_session(
        "sess-malformed-4", initial_state=SessionState.active
    )

    resp = client.get(
        f"/api/sessions/{sess.session_id}/events?from_sequence=not_an_int"
    )
    assert resp.status_code == 422
    env = ErrorEnvelope.model_validate(resp.json())
    assert env.code == "VALIDATION_ERROR"
