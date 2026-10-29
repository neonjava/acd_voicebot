"""Tests for /api/health and /api/ready endpoints, plus 404/405 error envelopes."""

import pytest
from fastapi.testclient import TestClient

from app.contracts.common import ErrorEnvelope
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_endpoint(client):
    """GET /api/health returns 200 with ok status and mock mode."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mode": "mock"}
    assert "X-Request-ID" in response.headers
    assert "X-Correlation-ID" in response.headers


def test_ready_endpoint(client):
    """GET /api/ready returns 200 with ready status and mock mode."""
    response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "mode": "mock"}
    assert "X-Request-ID" in response.headers
    assert "X-Correlation-ID" in response.headers


def test_correlation_id_propagated_when_valid(client):
    """Client-supplied valid X-Correlation-ID should be echoed back."""
    custom_corr_id = "custom-test-correlation-123"
    response = client.get("/api/health", headers={"X-Correlation-ID": custom_corr_id})
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == custom_corr_id


def test_invalid_correlation_id_rejected(client):
    """Invalid supplied X-Correlation-ID returns 422 with a safe ErrorEnvelope."""
    response = client.get(
        "/api/health", headers={"X-Correlation-ID": "invalid id with spaces"}
    )
    assert response.status_code == 422
    data = response.json()
    err = ErrorEnvelope.model_validate(data)
    assert err.code == "INVALID_CORRELATION_ID"
    assert err.retryable is False
    assert response.headers["X-Correlation-ID"] == err.correlation_id


def test_unknown_route_returns_404_error_envelope(client):
    """Accessing an unknown path must return 404 formatted as ErrorEnvelope."""
    response = client.get("/api/nonexistent-route-path")
    assert response.status_code == 404
    data = response.json()
    err = ErrorEnvelope.model_validate(data)
    assert err.code == "HTTP_404"
    assert err.message_safe_for_user == "Not Found"
    assert err.retryable is False
    assert "X-Correlation-ID" in response.headers
    assert "X-Request-ID" in response.headers


def test_unsupported_method_returns_405_error_envelope(client):
    """Accessing an endpoint with unsupported HTTP method returns 405 ErrorEnvelope."""
    response = client.delete("/api/health")
    assert response.status_code == 405
    data = response.json()
    err = ErrorEnvelope.model_validate(data)
    assert err.code == "HTTP_405"
    assert err.message_safe_for_user == "Method Not Allowed"
    assert err.retryable is False
    assert "X-Correlation-ID" in response.headers
    assert "X-Request-ID" in response.headers
