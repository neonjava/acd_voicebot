"""Preflight an entire workflow before invoking any mock tool."""

from collections.abc import Sequence

from app.agent import tools
from app.agent.state_machine import transition
from app.contracts.common import ErrorEnvelope, WorkflowState
from app.contracts.workflow import ApprovalRequest, WorkflowPlan, WorkflowResult


def _result(
    plan: WorkflowPlan,
    state: WorkflowState,
    *,
    outputs: dict[str, str] | None = None,
    error: ErrorEnvelope | None = None,
) -> WorkflowResult:
    return WorkflowResult(
        plan_id=plan.plan_id,
        session_id=plan.session_id,
        state=state,
        outputs=outputs or {},
        error=error,
    )


def execute(
    plan: WorkflowPlan, *, approvals: Sequence[ApprovalRequest] = ()
) -> WorkflowResult:
    """Execute once only if every required approval is explicitly granted.

    This call has no durable history. Calling it again may run the same steps again.
    """
    if not isinstance(plan, WorkflowPlan):
        raise TypeError("plan must be a WorkflowPlan")
    if plan.state in {
        WorkflowState.succeeded,
        WorkflowState.failed,
        WorkflowState.cancelled,
    }:
        raise ValueError("cannot execute a terminal workflow")

    steps = {step.step_id: step for step in plan.steps}
    for step in plan.steps:
        tools.validate_tool_call(step.tool_name, step.arguments)

    approval_by_step: dict[str, ApprovalRequest] = {}
    approval_ids: set[str] = set()
    for approval in approvals:
        if not isinstance(approval, ApprovalRequest):
            raise TypeError("approvals must be ApprovalRequest values")
        if (
            approval.session_id != plan.session_id
            or approval.plan_id != plan.plan_id
            or approval.step_id not in steps
        ):
            raise ValueError("approval does not match this session, plan, and step")
        if approval.approval_id in approval_ids or approval.step_id in approval_by_step:
            raise ValueError("duplicate workflow approval")
        approval_ids.add(approval.approval_id)
        approval_by_step[approval.step_id] = approval

    required_ids = {
        step.step_id
        for step in plan.steps
        if step.requires_approval or tools.TOOL_SPECS[step.tool_name].consequential
    }
    if any(approval.status == "rejected" for approval in approval_by_step.values()):
        return _result(plan, transition(plan.state, WorkflowState.cancelled))
    if any(
        approval_by_step.get(step_id) is None
        or approval_by_step[step_id].status != "approved"
        for step_id in required_ids
    ):
        if plan.state == WorkflowState.draft:
            target = transition(plan.state, WorkflowState.awaiting_approval)
        elif plan.state == WorkflowState.running:
            target = transition(plan.state, WorkflowState.paused)
        else:
            target = plan.state
        return _result(plan, target)

    running = (
        plan.state
        if plan.state == WorkflowState.running
        else transition(plan.state, WorkflowState.running)
    )
    outputs: dict[str, str] = {}
    try:
        for step in plan.steps:
            outputs[step.step_id] = tools.invoke_tool(step.tool_name, step.arguments)
    except Exception:
        return _result(
            plan,
            transition(running, WorkflowState.failed),
            outputs=outputs,
            error=ErrorEnvelope(
                code="WORKFLOW_TOOL_FAILED",
                message_safe_for_user="The mock workflow step failed.",
                retryable=False,
                correlation_id="workflow-mock",
            ),
        )
    return _result(plan, transition(running, WorkflowState.succeeded), outputs=outputs)
