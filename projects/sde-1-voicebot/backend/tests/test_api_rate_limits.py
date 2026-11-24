"""Tests for rate limiting middleware returning typed 429 ErrorEnvelope."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.contracts.common import ErrorEnvelope
from app.main import app, rate_limiter


@pytest.fixture(autouse=True)
def reset_limiter():
    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture
def client():
    return TestClient(app)


def test_rate_limit_allows_under_threshold(client):
    """Requests under configured limit are allowed normally."""
    with (
        patch.object(settings, "rate_limit_requests", 5),
        patch.object(settings, "rate_limit_window_seconds", 60),
    ):
        for _ in range(5):
            res = client.get("/api/health")
            assert res.status_code == 200


def test_rate_limit_exceeded_returns_429_typed_envelope(client):
    """Exceeding requests in window returns 429 with Retry-After and ErrorEnvelope."""
    with (
        patch.object(settings, "rate_limit_requests", 3),
        patch.object(settings, "rate_limit_window_seconds", 10),
    ):
        for _ in range(3):
            res = client.get("/api/health")
            assert res.status_code == 200

        # 4th request triggers rate limit
        res_blocked = client.get("/api/health")
        assert res_blocked.status_code == 429
        assert "Retry-After" in res_blocked.headers

        retry_after = int(res_blocked.headers["Retry-After"])
        assert retry_after > 0

        err = ErrorEnvelope.model_validate(res_blocked.json())
        assert err.code == "RATE_LIMITED"
        assert err.retryable is True
        assert err.details_redacted["retry_after"] == str(retry_after)
        assert "X-Request-ID" in res_blocked.headers
        assert "X-Correlation-ID" in res_blocked.headers
