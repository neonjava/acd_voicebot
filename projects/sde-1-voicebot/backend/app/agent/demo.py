"""Show pending, approved, and rejected mock workflows."""

from app.agent.executor import execute
from app.contracts.workflow import ApprovalRequest, WorkflowPlan, WorkflowStep


def main() -> None:
    plan = WorkflowPlan(
        plan_id="plan-demo",
        session_id="session-demo",
        steps=[
            WorkflowStep(
                step_id="note-1",
                tool_name="mock_save_note",
                arguments={"text": "Synthetic demo note"},
                requires_approval=False,  # Registry policy still requires approval.
            )
        ],
    )
    for status in ("pending", "approved", "rejected"):
        approval = ApprovalRequest(
            approval_id=f"approval-{status}",
            plan_id=plan.plan_id,
            step_id="note-1",
            session_id=plan.session_id,
            status=status,
        )
        result = execute(plan, approvals=[approval])
        print(f"{status}: {result.state.value}; outputs={result.outputs}")


if __name__ == "__main__":
    main()
