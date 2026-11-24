"""Week 3 W4 demo (mock mode): proposal -> plan -> backend approval -> progress,
then checkpoint/resume and an idempotent repeat.

Run from backend/: ``uv run python -m app.agent.week3_demo``
With real tools: ``WORKFLOW_TOOLS_MODE=real uv run python -m app.agent.week3_demo``
(needs ``--extra system``; opens one allow-listed page in your browser).
"""

from collections.abc import Mapping
from datetime import datetime, timezone

from app.agent import tools
from app.agent.approvals import InMemoryApprovalSource, approval_requests_for
from app.agent.checkpoint import WorkflowStore
from app.agent.executor import execute
from app.agent.proposals import plan_from_proposal
from app.contracts.workflow import WorkflowProposal, WorkflowStep

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _clock() -> datetime:
    return NOW


def main() -> int:
    runtime = tools.runtime_from_env()
    proposal = WorkflowProposal(
        proposal_id="demo-proposal",
        session_id="session-demo",
        correlation_id="correlation-demo",
        summary="Check memory, open YouTube and save a note",
        steps=[
            WorkflowStep(
                step_id="stats",
                tool_name="system_stats",
                arguments={},
                requires_approval=False,
            ),
            WorkflowStep(
                step_id="open",
                tool_name="open_url",
                arguments={"url": "https://www.youtube.com/"},
                requires_approval=False,
                depends_on=["stats"],
            ),
            WorkflowStep(
                step_id="note",
                tool_name="mock_save_note",
                arguments={"text": "Checked RAM and opened YouTube"},
                requires_approval=False,
                depends_on=["open"],
            ),
        ],
        source_ids=["transcript-0"],
    )
    plan = plan_from_proposal(proposal, allowed_hosts=runtime.allowed_hosts)
    print(f"mode={runtime.mode} plan={plan.plan_id} steps={len(plan.steps)}")

    backend = InMemoryApprovalSource()
    backend.register(approval_requests_for(plan, now=NOW))
    progress = lambda e: print(f"  progress {e.kind} step={e.step_id}")  # noqa: E731

    waiting = execute(
        plan, approval_source=backend, clock=_clock, runtime=runtime, on_audit=progress
    )
    print(f"before approval: {waiting.state.value}")

    backend.decide(f"{plan.plan_id}-approval-note", "approve", now=NOW)
    store = WorkflowStore()
    done = execute(
        plan,
        approval_source=backend,
        clock=_clock,
        runtime=runtime,
        on_audit=progress,
        store=store,
        idempotency_key="demo-run",
    )
    print(f"after approval: {done.state.value}")
    for step_id, output in done.outputs.items():
        print(f"  {step_id}: {output}")

    again = execute(
        plan,
        approval_source=backend,
        clock=_clock,
        runtime=runtime,
        store=store,
        idempotency_key="demo-run",
    )
    print(f"same idempotency key again: {again.state.value}, nothing re-run")

    # Checkpoint/resume: the second step fails once, then the plan resumes.
    resume_plan = plan.model_copy(update={"plan_id": "demo-resume"})
    failures = {"open": 1}

    def flaky(name: str, arguments: Mapping[str, str]) -> str:
        key = "open" if name == "open_url" else name
        if failures.get(key, 0):
            failures[key] -= 1
            raise RuntimeError("browser busy")
        return runtime.invoke(name, arguments)

    approval = backend.approvals_for_plan(plan.plan_id)[0].model_copy(
        update={"plan_id": "demo-resume", "approval_id": "demo-resume-note"}
    )
    resume_store = WorkflowStore()
    first = execute(
        resume_plan,
        approvals=[approval],
        clock=_clock,
        invoker=flaky,
        store=resume_store,
    )
    second = execute(
        resume_plan,
        approvals=[approval],
        clock=_clock,
        invoker=flaky,
        store=resume_store,
    )
    restored = [e.step_id for e in second.audit_events if e.kind == "step_restored"]
    print(f"resume: first={first.state.value} second={second.state.value}")
    print(f"  restored from checkpoint: {restored}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
