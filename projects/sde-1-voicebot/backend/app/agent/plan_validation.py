"""Dependency validation and deterministic execution order for workflow plans."""

from app.agent.errors import WorkflowPolicyError
from app.contracts.workflow import WorkflowPlan, WorkflowStep


def execution_order(plan: WorkflowPlan) -> list[WorkflowStep]:
    """Return steps in a dependency-respecting order, or raise a policy error.

    Missing dependencies and cycles are rejected. Among steps that are ready at
    the same time, the original plan order is kept, so the result is stable.
    """
    by_id = {step.step_id: step for step in plan.steps}
    for step in plan.steps:
        missing = [dep for dep in step.depends_on if dep not in by_id]
        if missing:
            raise WorkflowPolicyError(
                "WORKFLOW_MISSING_DEPENDENCY",
                f"step '{step.step_id}' depends on unknown step '{missing[0]}'",
            )

    remaining = {step.step_id: set(step.depends_on) for step in plan.steps}
    ordered: list[WorkflowStep] = []
    done: set[str] = set()
    while remaining:
        ready = [
            step
            for step in plan.steps
            if step.step_id in remaining and remaining[step.step_id] <= done
        ]
        if not ready:
            cycle = sorted(remaining)
            raise WorkflowPolicyError(
                "WORKFLOW_DEPENDENCY_CYCLE",
                f"dependency cycle among steps: {', '.join(cycle)}",
            )
        for step in ready:
            ordered.append(step)
            done.add(step.step_id)
            del remaining[step.step_id]
    return ordered
