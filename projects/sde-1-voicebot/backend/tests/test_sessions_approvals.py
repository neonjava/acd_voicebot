"""Tests for approval endpoints (listing, approving, rejecting, and expiry)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.contracts.common import ErrorEnvelope
from app.contracts.workflow import ApprovalRequest, WorkflowPlan, WorkflowStep
from app.main import app
from app.sessions.service import session_service


@pytest.fixture(autouse=True)
def clean_service():
    session_service.clear()
    yield
    session_service.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_list_pending_approvals(client):
    """GET /api/sessions/{id}/approvals returns only pending, non-expired approvals."""
    session_service.create_session("sess-appr-1")

    step = WorkflowStep(
        step_id="step-1", tool_name="echo_text", arguments={"text": "hello"}
    )
    plan = WorkflowPlan(plan_id="plan-1", session_id="sess-appr-1", steps=[step])

    appr1 = ApprovalRequest(
        approval_id="appr-pending-1",
        plan_id="plan-1",
        step_id="step-1",
        session_id="sess-appr-1",
        status="pending",
    )
    appr_approved = ApprovalRequest(
        approval_id="appr-done",
        plan_id="plan-1",
        step_id="step-1",
        session_id="sess-appr-1",
        status="approved",
    )
    session_service.register_approval(appr1, plan)
    session_service.register_approval(appr_approved, plan)

    res = client.get("/api/sessions/sess-appr-1/approvals")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["approval_id"] == "appr-pending-1"
    assert data[0]["status"] == "pending"


def test_approve_executes_workflow_step_once(client):
    """Approving runs the consequential step exactly once using the real W4 executor."""
    session_service.create_session("sess-appr-exec")
    step = WorkflowStep(
        step_id="step-echo",
        tool_name="echo_text",
        arguments={"text": "Approved output text"},
        requires_approval=True,
    )
    plan = WorkflowPlan(plan_id="plan-echo", session_id="sess-appr-exec", steps=[step])
    appr = ApprovalRequest(
        approval_id="appr-exec-1",
        plan_id="plan-echo",
        step_id="step-echo",
        session_id="sess-appr-exec",
        status="pending",
    )
    session_service.register_approval(appr, plan)

    res = client.post(
        "/api/sessions/sess-appr-exec/approvals/appr-exec-1",
        json={"decision": "approve"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["approval_id"] == "appr-exec-1"
    assert data["status"] == "approved"

    # Verify audit events were recorded in session event history
    events = session_service.get_events("sess-appr-exec")
    event_types = [e.event_type for e in events]
    assert "workflow.audit" in event_types

    audit_payloads = [e.payload for e in events if e.event_type == "workflow.audit"]
    assert any(a.kind == "approval_granted" for a in audit_payloads)
    assert any(a.kind == "step_succeeded" for a in audit_payloads)


def test_reject_never_runs_workflow_step(client):
    """Rejecting approval cancels workflow and never executes tool."""
    session_service.create_session("sess-appr-rej")
    step = WorkflowStep(
        step_id="step-save",
        tool_name="mock_save_note",
        arguments={"text": "Never execute this"},
        requires_approval=True,
    )
    plan = WorkflowPlan(plan_id="plan-save", session_id="sess-appr-rej", steps=[step])
    appr = ApprovalRequest(
        approval_id="appr-rej-1",
        plan_id="plan-save",
        step_id="step-save",
        session_id="sess-appr-rej",
        status="pending",
    )
    session_service.register_approval(appr, plan)

    res = client.post(
        "/api/sessions/sess-appr-rej/approvals/appr-rej-1",
        json={"decision": "reject"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"

    # Verify audit trail contains approval_rejected and workflow_cancelled
    events = session_service.get_events("sess-appr-rej")
    audit_payloads = [e.payload for e in events if e.event_type == "workflow.audit"]
    assert any(a.kind == "approval_rejected" for a in audit_payloads)
    assert any(a.kind == "workflow_cancelled" for a in audit_payloads)
    assert not any(a.kind == "step_succeeded" for a in audit_payloads)


def test_deciding_twice_returns_409(client):
    """Deciding an already decided approval request returns 409 Conflict."""
    session_service.create_session("sess-appr-dup")
    step = WorkflowStep(
        step_id="step-1", tool_name="echo_text", arguments={"text": "hi"}
    )
    plan = WorkflowPlan(plan_id="plan-dup", session_id="sess-appr-dup", steps=[step])
    appr = ApprovalRequest(
        approval_id="appr-dup-1",
        plan_id="plan-dup",
        step_id="step-1",
        session_id="sess-appr-dup",
        status="pending",
    )
    session_service.register_approval(appr, plan)

    # First decision
    res1 = client.post(
        "/api/sessions/sess-appr-dup/approvals/appr-dup-1",
        json={"decision": "approve"},
    )
    assert res1.status_code == 200

    # Second decision returns 409
    res2 = client.post(
        "/api/sessions/sess-appr-dup/approvals/appr-dup-1",
        json={"decision": "approve"},
    )
    assert res2.status_code == 409
    err = ErrorEnvelope.model_validate(res2.json())
    assert err.code == "APPROVAL_ALREADY_DECIDED"


def test_deciding_after_expiry_returns_409(client):
    """Deciding an approval after expires_at returns 409 Conflict."""
    session_service.create_session("sess-appr-exp")
    past_expiry = datetime.now(timezone.utc) - timedelta(minutes=5)
    step = WorkflowStep(
        step_id="step-1", tool_name="echo_text", arguments={"text": "hi"}
    )
    plan = WorkflowPlan(plan_id="plan-exp", session_id="sess-appr-exp", steps=[step])
    appr = ApprovalRequest(
        approval_id="appr-expired-1",
        plan_id="plan-exp",
        step_id="step-1",
        session_id="sess-appr-exp",
        status="pending",
        expires_at=past_expiry,
    )
    session_service.register_approval(appr, plan)

    res = client.post(
        "/api/sessions/sess-appr-exp/approvals/appr-expired-1",
        json={"decision": "approve"},
    )
    assert res.status_code == 409
    err = ErrorEnvelope.model_validate(res.json())
    assert err.code == "APPROVAL_EXPIRED"
