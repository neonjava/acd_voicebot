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


def test_deciding_approval_on_expired_session_returns_409_and_runs_nothing(client):
    """Approving on an expired session returns 409 and runs no consequential tools."""
    session_service.create_session("sess-expired-session")
    step = WorkflowStep(
        step_id="step-exp-session",
        tool_name="echo_text",
        arguments={"text": "should never execute"},
        requires_approval=True,
    )
    plan = WorkflowPlan(
        plan_id="plan-exp-session",
        session_id="sess-expired-session",
        steps=[step],
    )
    appr = ApprovalRequest(
        approval_id="appr-exp-session-1",
        plan_id="plan-exp-session",
        step_id="step-exp-session",
        session_id="sess-expired-session",
        status="pending",
    )
    session_service.register_approval(appr, plan)

    # Expire the session
    session_service.expire_session("sess-expired-session")

    # Attempt to approve
    res = client.post(
        "/api/sessions/sess-expired-session/approvals/appr-exp-session-1",
        json={"decision": "approve"},
    )
    assert res.status_code == 409
    err = ErrorEnvelope.model_validate(res.json())
    assert err.code == "APPROVAL_EXPIRED"

    # Verify tool was NOT executed and no audit event was emitted
    events = session_service.get_events("sess-expired-session")
    audit_payloads = [e.payload for e in events if e.event_type == "workflow.audit"]
    assert not any(a.kind == "step_succeeded" for a in audit_payloads)


def test_deciding_approval_with_missing_plan_returns_409(client):
    """Deciding an approval whose plan is missing returns 409 and runs nothing."""
    session_service.create_session("sess-missing-plan")
    appr = ApprovalRequest(
        approval_id="appr-missing-plan-1",
        plan_id="plan-does-not-exist",
        step_id="step-missing",
        session_id="sess-missing-plan",
        status="pending",
    )
    # Inject directly without a plan to test defensive missing plan handling
    session_service._approvals[appr.approval_id] = appr

    res = client.post(
        "/api/sessions/sess-missing-plan/approvals/appr-missing-plan-1",
        json={"decision": "approve"},
    )
    assert res.status_code == 409
    err = ErrorEnvelope.model_validate(res.json())
    assert err.code == "WORKFLOW_PLAN_MISSING"

    # Verify tool was NOT executed
    events = session_service.get_events("sess-missing-plan")
    assert len(events) == 0


def test_register_approval_requires_plan():
    """register_approval raises ValueError if plan is omitted."""
    appr = ApprovalRequest(
        approval_id="appr-no-plan",
        plan_id="plan-none",
        step_id="step-none",
        session_id="sess-test",
        status="pending",
    )
    with pytest.raises(ValueError, match="Workflow plan is required"):
        session_service.register_approval(appr, None)


def test_deciding_approval_after_stop_returns_409_and_runs_nothing(client):
    """Approving after session stop (completed state) returns 409 and runs no tool."""
    from app.contracts.common import SessionState

    session_service.create_session("sess-stop-appr", initial_state=SessionState.active)
    step = WorkflowStep(
        step_id="step-stop",
        tool_name="echo_text",
        arguments={"text": "should never execute"},
        requires_approval=True,
    )
    plan = WorkflowPlan(
        plan_id="plan-stop",
        session_id="sess-stop-appr",
        steps=[step],
    )
    appr = ApprovalRequest(
        approval_id="appr-stop-1",
        plan_id="plan-stop",
        step_id="step-stop",
        session_id="sess-stop-appr",
        status="pending",
    )
    session_service.register_approval(appr, plan)

    # Stop the session (completed state)
    res_stop = client.post("/api/sessions/sess-stop-appr/stop")
    assert res_stop.status_code == 200
    assert res_stop.json()["state"] == "completed"

    # Approving after stop must return 409
    res = client.post(
        "/api/sessions/sess-stop-appr/approvals/appr-stop-1",
        json={"decision": "approve"},
    )
    assert res.status_code == 409
    err = ErrorEnvelope.model_validate(res.json())
    assert err.code == "SESSION_TERMINAL_STATE"

    # Verify no tool execution occurred
    events = session_service.get_events("sess-stop-appr")
    audit_payloads = [e.payload for e in events if e.event_type == "workflow.audit"]
    assert not any(a.kind == "step_succeeded" for a in audit_payloads)


def test_deciding_approval_on_failed_session_returns_409(client):
    """Approving on a failed session returns 409 and runs no tool."""
    from app.contracts.common import SessionState

    session_service.create_session("sess-failed-appr")
    step = WorkflowStep(
        step_id="step-fail",
        tool_name="echo_text",
        arguments={"text": "should never execute"},
        requires_approval=True,
    )
    plan = WorkflowPlan(
        plan_id="plan-fail",
        session_id="sess-failed-appr",
        steps=[step],
    )
    appr = ApprovalRequest(
        approval_id="appr-fail-1",
        plan_id="plan-fail",
        step_id="step-fail",
        session_id="sess-failed-appr",
        status="pending",
    )
    session_service.register_approval(appr, plan)

    # Transition session to failed
    session_service.transition("sess-failed-appr", SessionState.failed)

    # Approving on failed session must return 409
    res = client.post(
        "/api/sessions/sess-failed-appr/approvals/appr-fail-1",
        json={"decision": "approve"},
    )
    assert res.status_code == 409
    err = ErrorEnvelope.model_validate(res.json())
    assert err.code == "SESSION_TERMINAL_STATE"


def test_approve_with_future_expiry_succeeds_and_executes_step(client):
    """Approving an approval with future expires_at passes clock and executes step."""
    session_service.create_session("sess-appr-expiry")
    step = WorkflowStep(
        step_id="step-exp",
        tool_name="echo_text",
        arguments={"text": "Expiring approval text"},
        requires_approval=True,
    )
    plan = WorkflowPlan(
        plan_id="plan-exp",
        session_id="sess-appr-expiry",
        steps=[step],
    )
    future_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    appr = ApprovalRequest(
        approval_id="appr-future-exp",
        plan_id="plan-exp",
        step_id="step-exp",
        session_id="sess-appr-expiry",
        status="pending",
        expires_at=future_expiry,
    )
    session_service.register_approval(appr, plan)

    res = client.post(
        "/api/sessions/sess-appr-expiry/approvals/appr-future-exp",
        json={"decision": "approve"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["approval_id"] == "appr-future-exp"
    assert data["status"] == "approved"

    events = session_service.get_events("sess-appr-expiry")
    audits = [e.payload for e in events if e.event_type == "workflow.audit"]
    assert any(a.kind == "step_succeeded" for a in audits)


def test_approval_remains_pending_when_execution_fails(client):
    """If workflow execution fails, approval status is not saved as approved."""
    from unittest.mock import patch

    from app.sessions.gateways import GatewayError

    session_service.create_session("sess-appr-fail")
    step = WorkflowStep(
        step_id="step-fail-cmd",
        tool_name="echo_text",
        arguments={"text": "Fail text"},
        requires_approval=True,
    )
    plan = WorkflowPlan(
        plan_id="plan-fail-cmd",
        session_id="sess-appr-fail",
        steps=[step],
    )
    appr = ApprovalRequest(
        approval_id="appr-fail-cmd",
        plan_id="plan-fail-cmd",
        step_id="step-fail-cmd",
        session_id="sess-appr-fail",
        status="pending",
    )
    session_service.register_approval(appr, plan)

    envelope = ErrorEnvelope(
        code="WORKFLOW_EXECUTION_FAILED",
        message_safe_for_user="Workflow execution failed.",
        retryable=False,
        correlation_id="corr-appr-fail",
    )

    with patch(
        "app.sessions.gateways.WorkflowGateway.execute_plan",
        side_effect=GatewayError(envelope),
    ):
        res = client.post(
            "/api/sessions/sess-appr-fail/approvals/appr-fail-cmd",
            json={"decision": "approve"},
        )
        assert res.status_code == 502

    # Verify approval remains pending (not permanently locked in 409 already decided)
    pending = session_service.get_pending_approvals("sess-appr-fail")
    assert len(pending) == 1
    assert pending[0].approval_id == "appr-fail-cmd"
    assert pending[0].status == "pending"


def test_multi_step_plan_execution_with_multiple_approvals(client):
    """Multi-step plan executes steps as each required approval completes."""
    session_service.create_session("sess-multi-plan")
    step1 = WorkflowStep(
        step_id="step-1",
        tool_name="echo_text",
        arguments={"text": "First action"},
        requires_approval=True,
    )
    step2 = WorkflowStep(
        step_id="step-2",
        tool_name="echo_text",
        arguments={"text": "Second action"},
        requires_approval=True,
        depends_on=["step-1"],
    )
    plan = WorkflowPlan(
        plan_id="plan-multi",
        session_id="sess-multi-plan",
        steps=[step1, step2],
    )
    appr1 = ApprovalRequest(
        approval_id="appr-multi-1",
        plan_id="plan-multi",
        step_id="step-1",
        session_id="sess-multi-plan",
        status="pending",
    )
    appr2 = ApprovalRequest(
        approval_id="appr-multi-2",
        plan_id="plan-multi",
        step_id="step-2",
        session_id="sess-multi-plan",
        status="pending",
    )
    session_service.register_approval(appr1, plan)
    session_service.register_approval(appr2, plan)

    # Approve step 1
    res1 = client.post(
        "/api/sessions/sess-multi-plan/approvals/appr-multi-1",
        json={"decision": "approve"},
    )
    assert res1.status_code == 200
    assert res1.json()["status"] == "approved"

    # Step 2 is still pending
    pending = session_service.get_pending_approvals("sess-multi-plan")
    assert len(pending) == 1
    assert pending[0].approval_id == "appr-multi-2"

    # Approve step 2
    res2 = client.post(
        "/api/sessions/sess-multi-plan/approvals/appr-multi-2",
        json={"decision": "approve"},
    )
    assert res2.status_code == 200
    assert res2.json()["status"] == "approved"

    # Both steps executed
    events = session_service.get_events("sess-multi-plan")
    audits = [e.payload for e in events if e.event_type == "workflow.audit"]
    succeeded_steps = [a.step_id for a in audits if a.kind == "step_succeeded"]
    assert "step-1" in succeeded_steps
    assert "step-2" in succeeded_steps


def test_register_approval_validates_plan_consistency():
    """register_approval enforces matching plan_id, session_id, and step_id."""
    step = WorkflowStep(
        step_id="step-ok",
        tool_name="echo_text",
        arguments={"text": "consistent"},
        requires_approval=True,
    )
    plan = WorkflowPlan(
        plan_id="plan-ok",
        session_id="sess-ok",
        steps=[step],
    )

    # Mismatched plan_id
    bad_plan_id = ApprovalRequest(
        approval_id="appr-bad-1",
        plan_id="plan-mismatch",
        step_id="step-ok",
        session_id="sess-ok",
    )
    with pytest.raises(ValueError, match="does not match plan"):
        session_service.register_approval(bad_plan_id, plan)

    # Mismatched session_id
    bad_sess_id = ApprovalRequest(
        approval_id="appr-bad-2",
        plan_id="plan-ok",
        step_id="step-ok",
        session_id="sess-mismatch",
    )
    with pytest.raises(ValueError, match="does not match plan"):
        session_service.register_approval(bad_sess_id, plan)

    # Mismatched step_id
    bad_step_id = ApprovalRequest(
        approval_id="appr-bad-3",
        plan_id="plan-ok",
        step_id="step-nonexistent",
        session_id="sess-ok",
    )
    with pytest.raises(ValueError, match="not in plan steps"):
        session_service.register_approval(bad_step_id, plan)
