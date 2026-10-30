"""Documented workflow state transitions."""

from app.contracts.common import WorkflowState

_ALLOWED: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.draft: frozenset(
        {
            WorkflowState.awaiting_approval,
            WorkflowState.running,
            WorkflowState.cancelled,
        }
    ),
    WorkflowState.awaiting_approval: frozenset(
        {WorkflowState.running, WorkflowState.cancelled}
    ),
    WorkflowState.running: frozenset(
        {
            WorkflowState.paused,
            WorkflowState.succeeded,
            WorkflowState.failed,
            WorkflowState.cancelled,
        }
    ),
    WorkflowState.paused: frozenset({WorkflowState.running, WorkflowState.cancelled}),
    WorkflowState.succeeded: frozenset(),
    WorkflowState.failed: frozenset(),
    WorkflowState.cancelled: frozenset(),
}


def transition(current: WorkflowState, target: WorkflowState) -> WorkflowState:
    """Return a legal target state, or reject the transition."""
    if not isinstance(current, WorkflowState) or not isinstance(target, WorkflowState):
        raise TypeError("workflow states must be WorkflowState values")
    if target not in _ALLOWED[current]:
        raise ValueError(
            f"illegal workflow transition: {current.value} -> {target.value}"
        )
    return target
