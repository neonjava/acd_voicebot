"""Show approved versus rejected mock workflows and the Week 2 safety checks."""

from collections.abc import Mapping
from datetime import datetime, timezone

from app.agent import tools
from app.agent.errors import WorkflowPolicyError
from app.agent.executor import execute
from app.contracts.workflow import ApprovalRequest, WorkflowPlan, WorkflowStep

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _plan() -> WorkflowPlan:
    return WorkflowPlan(
        plan_id="plan-demo",
        session_id="session-demo",
        steps=[
            WorkflowStep(
                step_id="echo-1",
                tool_name="echo_text",
                arguments={"text": "Synthetic demo text"},
                requires_approval=False,
            ),
            WorkflowStep(
                step_id="note-1",
                tool_name="mock_save_note",
                arguments={"text": "Synthetic demo note"},
                requires_approval=False,  # Registry policy still requires approval.
                depends_on=["echo-1"],
            ),
        ],
    )


def _approval(status: str, *, expires_at: datetime | None = None) -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=f"approval-{status}",
        plan_id="plan-demo",
        step_id="note-1",
        session_id="session-demo",
        status=status,
        expires_at=expires_at,
    )


def main() -> None:
    plan = _plan()
    print("1. Approval outcomes (note-1 depends on echo-1)")
    for status in ("pending", "approved", "rejected"):
        result = execute(plan, approvals=[_approval(status)])
        kinds = ",".join(event.kind for event in result.audit_events)
        print(f"   {status}: {result.state.value}; outputs={result.outputs}")
        print(f"      audit={kinds}")

    expired = execute(
        plan,
        approvals=[_approval("approved", expires_at=NOW)],
        clock=lambda: NOW,
    )
    print(f"   expired approval: {expired.state.value}; outputs={expired.outputs}")

    print("2. Plans rejected before any tool runs")
    bad_plans = {
        "cycle": [
            WorkflowStep(
                step_id="a",
                tool_name="echo_text",
                arguments={"text": "x"},
                depends_on=["b"],
            ),
            WorkflowStep(
                step_id="b",
                tool_name="echo_text",
                arguments={"text": "x"},
                depends_on=["a"],
            ),
        ],
        "unknown tool": [
            WorkflowStep(step_id="a", tool_name="shell", arguments={"text": "ls"})
        ],
    }
    for label, steps in bad_plans.items():
        try:
            execute(WorkflowPlan(plan_id="p", session_id="s", steps=steps))
        except WorkflowPolicyError as error:
            print(f"   {label}: {error.code}")
    try:
        execute(
            plan,
            approvals=[_approval("approved")],
            granted_scopes=frozenset({"text:read"}),
        )
    except WorkflowPolicyError as error:
        print(f"   missing notes:write scope: {error.code}")

    print("3. Bounded retry: idempotent echo times out once, then succeeds")
    echo_attempts: list[int] = []

    def flaky(name: str, arguments: Mapping[str, str]) -> str:
        if name == "echo_text":
            echo_attempts.append(1)
            if len(echo_attempts) == 1:
                raise TimeoutError
        return tools.invoke_tool(name, arguments)

    retried = execute(
        plan, approvals=[_approval("approved")], max_retries=1, invoker=flaky
    )
    print(f"   {retried.state.value}; echo attempts={len(echo_attempts)}")


if __name__ == "__main__":
    main()
