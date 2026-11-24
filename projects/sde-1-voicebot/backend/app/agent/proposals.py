"""Turn a reasoning WorkflowProposal into a WorkflowPlan the executor can run.

A proposal is only a suggestion from W3. Nothing here runs a tool: every step
is checked against the tool registry and its arguments, and dependencies are
checked for gaps and cycles. Approval rules are not taken from the proposal:
the executor still requires approval for every consequential tool.
"""

from app.agent import tools
from app.agent.plan_validation import execution_order
from app.contracts.workflow import WorkflowPlan, WorkflowProposal


def plan_from_proposal(
    proposal: WorkflowProposal,
    *,
    allowed_hosts: frozenset[str] = tools.DEFAULT_ALLOWED_HOSTS,
) -> WorkflowPlan:
    """Validate a proposal and return a draft plan with the same ID and steps.

    Raises ``WorkflowPolicyError`` for an unknown tool, invalid arguments, a
    site that is not allow-listed, a missing dependency or a cycle.
    """
    if not isinstance(proposal, WorkflowProposal):
        raise TypeError("proposal must be a WorkflowProposal")
    for step in proposal.steps:
        tools.validate_tool_call(
            step.tool_name, step.arguments, allowed_hosts=allowed_hosts
        )
    plan = WorkflowPlan(
        plan_id=proposal.proposal_id,
        session_id=proposal.session_id,
        steps=[step.model_copy(deep=True) for step in proposal.steps],
    )
    execution_order(plan)
    return plan
