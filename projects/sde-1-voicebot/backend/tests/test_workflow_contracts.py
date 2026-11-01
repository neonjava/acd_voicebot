"""Schema boundaries for workflow data."""

import pytest
from pydantic import ValidationError

from app.contracts.common import WorkflowState
from app.contracts.workflow import (
    ApprovalRequest,
    ToolSpec,
    WorkflowPlan,
    WorkflowResult,
    WorkflowStep,
)


def step(**changes: object) -> WorkflowStep:
    data: dict[str, object] = {
        "step_id": "step-1",
        "tool_name": "echo_text",
        "arguments": {"text": "hello"},
    }
    data.update(changes)
    return WorkflowStep.model_validate(data)


def test_default_plan_and_approval_states() -> None:
    plan = WorkflowPlan(plan_id="plan-1", session_id="session-1", steps=[step()])
    approval = ApprovalRequest(
        approval_id="approval-1",
        plan_id=plan.plan_id,
        session_id=plan.session_id,
        step_id="step-1",
    )
    assert plan.state is WorkflowState.draft
    assert approval.status == "pending"
    assert step().requires_approval is True


@pytest.mark.parametrize("bad_id", ["", "  "])
def test_blank_ids_rejected(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        WorkflowPlan(plan_id=bad_id, session_id="session-1", steps=[step()])
    with pytest.raises(ValidationError):
        ApprovalRequest(
            approval_id="approval-1",
            plan_id="plan-1",
            session_id="session-1",
            step_id=bad_id,
        )


def test_empty_duplicate_and_extra_plan_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkflowPlan(plan_id="plan-1", session_id="session-1", steps=[])
    with pytest.raises(ValidationError):
        WorkflowPlan(plan_id="plan-1", session_id="session-1", steps=[step(), step()])
    with pytest.raises(ValidationError):
        WorkflowPlan.model_validate(
            {
                "plan_id": "plan-1",
                "session_id": "session-1",
                "steps": [step().model_dump()],
                "unexpected": "value",
            }
        )


@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_boolean_policy_fields_are_strict(value: object) -> None:
    with pytest.raises(ValidationError):
        step(requires_approval=value)
    with pytest.raises(ValidationError):
        ToolSpec(name="echo_text", description="Echo", consequential=value)


def test_reject_unknown_states_and_approval_status() -> None:
    with pytest.raises(ValidationError):
        WorkflowPlan(
            plan_id="plan-1", session_id="session-1", steps=[step()], state="unknown"
        )
    with pytest.raises(ValidationError):
        ApprovalRequest(
            approval_id="approval-1",
            plan_id="plan-1",
            session_id="session-1",
            step_id="step-1",
            status="maybe",
        )


def test_result_defaults_and_error_type() -> None:
    result = WorkflowResult(
        plan_id="plan-1", session_id="session-1", state=WorkflowState.succeeded
    )
    assert result.outputs == {}
    assert result.error is None
