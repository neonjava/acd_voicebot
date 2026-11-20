"""Tests for local authorization boundary (VOICEBOT_LAUNCH_TOKEN)."""

import logging
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.contracts.common import ErrorEnvelope
from app.contracts.workflow import ApprovalRequest, WorkflowPlan, WorkflowStep
from app.main import app
from app.sessions.logging import StructuredRedactingFormatter
from app.sessions.service import session_service

TEST_TOKEN = "test-launch-token-xyz-12345"


@pytest.fixture
def client():
    session_service.clear()
    return TestClient(app)


def test_auth_off_by_default(client):
    """Unauthenticated access passes when launch_token is unset."""
    with patch.object(settings, "launch_token", None):
        res = client.get("/api/ready")
        assert res.status_code == 200
        assert res.json()["auth"] == "off"

        res_health = client.get("/api/health")
        assert res_health.status_code == 200

        res_create = client.post("/api/sessions", json={"session_id": "sess-no-auth"})
        assert res_create.status_code == 201


def test_health_is_exempt_from_auth(client):
    """GET /api/health must return 200 without Authorization even when token is set."""
    with patch.object(settings, "launch_token", TEST_TOKEN):
        res = client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


def test_all_route_groups_reject_unauthenticated_requests(client):
    """Every /api/* route except health returns 401 without valid Bearer token."""
    with patch.object(settings, "launch_token", TEST_TOKEN):
        # Setup an existing session and approval for deep route checks
        with patch.object(settings, "launch_token", None):
            session_service.create_session("sess-auth-target")
            step = WorkflowStep(
                step_id="step-1", tool_name="echo_text", arguments={"text": "hi"}
            )
            plan = WorkflowPlan(
                plan_id="plan-1", session_id="sess-auth-target", steps=[step]
            )
            appr = ApprovalRequest(
                approval_id="appr-1",
                plan_id="plan-1",
                step_id="step-1",
                session_id="sess-auth-target",
            )
            session_service.register_approval(appr, plan)

        endpoints = [
            ("GET", "/api/ready", None),
            ("POST", "/api/sessions/mock", {}),
            ("POST", "/api/sessions", {"session_id": "sess-new-1"}),
            ("GET", "/api/sessions/sess-auth-target", None),
            ("POST", "/api/sessions/sess-auth-target/pause", {}),
            ("POST", "/api/sessions/sess-auth-target/resume", {}),
            ("POST", "/api/sessions/sess-auth-target/stop", {}),
            ("POST", "/api/sessions/sess-auth-target/expire", None),
            ("GET", "/api/sessions/sess-auth-target/events", None),
            ("GET", "/api/sessions/sess-auth-target/approvals", None),
            (
                "POST",
                "/api/sessions/sess-auth-target/approvals/appr-1",
                {"decision": "approve"},
            ),
        ]

        for method, path, json_body in endpoints:
            # 1. Missing header
            res = client.request(method, path, json=json_body)
            assert res.status_code == 401, (
                f"{method} {path} should return 401 on missing auth"
            )
            err = ErrorEnvelope.model_validate(res.json())
            assert err.code == "AUTH_REQUIRED"

            # 2. Invalid / wrong token
            res_bad = client.request(
                method,
                path,
                json=json_body,
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert res_bad.status_code == 401, (
                f"{method} {path} should return 401 on wrong token"
            )


def test_authenticated_requests_succeed_with_correct_token(client):
    """Supplying correct Authorization Bearer token permits request."""
    with patch.object(settings, "launch_token", TEST_TOKEN):
        headers = {"Authorization": f"Bearer {TEST_TOKEN}"}
        res = client.get("/api/ready", headers=headers)
        assert res.status_code == 200
        assert res.json()["auth"] == "token"

        res_create = client.post(
            "/api/sessions",
            json={"session_id": "sess-auth-pass"},
            headers=headers,
        )
        assert res_create.status_code == 201


def test_launch_token_never_appears_in_logs_or_responses(client, caplog):
    """Bearer token must be redacted from logs and never returned in response."""
    formatter = StructuredRedactingFormatter()
    record = logging.LogRecord(
        name="test.auth",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg=f"Request received with Authorization: Bearer {TEST_TOKEN}",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    assert TEST_TOKEN not in formatted
    assert "Bearer [REDACTED]" in formatted

    with patch.object(settings, "launch_token", TEST_TOKEN):
        res = client.get(
            "/api/ready", headers={"Authorization": f"Bearer {TEST_TOKEN}"}
        )
        assert TEST_TOKEN not in res.text
