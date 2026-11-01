"""Actual W3 reasoning result to W4 mock echo handoff when W3 is present."""

import pytest

from app.agent.executor import execute
from app.contracts.common import WorkflowState
from app.contracts.workflow import ApprovalRequest, WorkflowPlan, WorkflowStep


def test_reasoning_answer_requires_explicit_matching_approval() -> None:
    pytest.importorskip("app.contracts.reasoning", reason="W3 PR is not merged yet")
    from app.contracts.reasoning import ContextItem, ReasoningRequest, SourceReference
    from app.reasoning.mock import reason

    request = ReasoningRequest(
        request_id="request-1",
        session_id="session-1",
        question="What does the synthetic context say?",
        context=[
            ContextItem(
                item_id="item-1",
                text="Synthetic context only",
                source=SourceReference(
                    source_id="source-1", locator="synthetic-1", kind="synthetic_screen"
                ),
            )
        ],
    )
    result = reason(request)
    work = WorkflowPlan(
        plan_id="plan-1",
        session_id=result.session_id,
        steps=[
            WorkflowStep(
                step_id="echo-1",
                tool_name="echo_text",
                arguments={"text": result.answer},
            )
        ],
    )
    approved = ApprovalRequest(
        approval_id="approval-1",
        session_id=work.session_id,
        plan_id=work.plan_id,
        step_id="echo-1",
        status="approved",
    )
    rejected = approved.model_copy(update={"status": "rejected"})
    assert execute(work).state is WorkflowState.awaiting_approval
    assert execute(work, approvals=[rejected]).state is WorkflowState.cancelled
    executed = execute(work, approvals=[approved])
    assert executed.state is WorkflowState.succeeded
    assert executed.outputs == {"echo-1": result.answer}
