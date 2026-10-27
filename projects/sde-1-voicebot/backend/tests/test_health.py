"""Tests for /api/health and /api/ready endpoints."""

import pytest
from fastapi.testclient import TestClient

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
    # invalid character like space or dollar sign
    response = client.get(
        "/api/health", headers={"X-Correlation-ID": "invalid id with spaces"}
    )
    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "INVALID_CORRELATION_ID"
    assert data["retryable"] is False
    assert "correlation_id" in data
    # Header should return the new safe correlation ID
    assert response.headers["X-Correlation-ID"] == data["correlation_id"]
