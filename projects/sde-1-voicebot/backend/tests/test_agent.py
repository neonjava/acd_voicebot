"""State-machine, approval, and harmless-tool behavior."""

import pytest

from app.agent import tools
from app.agent.executor import execute
from app.agent.state_machine import transition
from app.contracts.common import WorkflowState
from app.contracts.workflow import ApprovalRequest, WorkflowPlan, WorkflowStep


def plan(
    *steps: WorkflowStep, state: WorkflowState = WorkflowState.draft
) -> WorkflowPlan:
    return WorkflowPlan(
        plan_id="plan-1", session_id="session-1", steps=list(steps), state=state
    )


def step(
    step_id: str = "step-1",
    tool_name: str = "echo_text",
    *,
    requires_approval: bool = True,
    arguments: dict[str, str] | None = None,
) -> WorkflowStep:
    return WorkflowStep(
        step_id=step_id,
        tool_name=tool_name,
        arguments={"text": "hello"} if arguments is None else arguments,
        requires_approval=requires_approval,
    )


def approval(
    step_id: str = "step-1", status: str = "approved", **changes: str
) -> ApprovalRequest:
    data = {
        "approval_id": f"approval-{step_id}",
        "plan_id": "plan-1",
        "session_id": "session-1",
        "step_id": step_id,
        "status": status,
    }
    data.update(changes)
    return ApprovalRequest.model_validate(data)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (WorkflowState.draft, WorkflowState.awaiting_approval),
        (WorkflowState.draft, WorkflowState.running),
        (WorkflowState.draft, WorkflowState.cancelled),
        (WorkflowState.awaiting_approval, WorkflowState.running),
        (WorkflowState.awaiting_approval, WorkflowState.cancelled),
        (WorkflowState.running, WorkflowState.paused),
        (WorkflowState.running, WorkflowState.succeeded),
        (WorkflowState.running, WorkflowState.failed),
        (WorkflowState.running, WorkflowState.cancelled),
        (WorkflowState.paused, WorkflowState.running),
        (WorkflowState.paused, WorkflowState.cancelled),
    ],
)
def test_legal_transitions(current: WorkflowState, target: WorkflowState) -> None:
    assert transition(current, target) is target


def test_every_other_transition_is_illegal() -> None:
    legal = {
        (WorkflowState.draft, WorkflowState.awaiting_approval),
        (WorkflowState.draft, WorkflowState.running),
        (WorkflowState.draft, WorkflowState.cancelled),
        (WorkflowState.awaiting_approval, WorkflowState.running),
        (WorkflowState.awaiting_approval, WorkflowState.cancelled),
        (WorkflowState.running, WorkflowState.paused),
        (WorkflowState.running, WorkflowState.succeeded),
        (WorkflowState.running, WorkflowState.failed),
        (WorkflowState.running, WorkflowState.cancelled),
        (WorkflowState.paused, WorkflowState.running),
        (WorkflowState.paused, WorkflowState.cancelled),
    }
    for current in WorkflowState:
        for target in WorkflowState:
            if (current, target) not in legal:
                with pytest.raises(ValueError):
                    transition(current, target)


def test_pending_and_rejected_run_zero_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(tools, "invoke_tool", lambda name, args: calls.append(name))
    work = plan(step(tool_name="mock_save_note", requires_approval=False))
    assert execute(work).state is WorkflowState.awaiting_approval
    assert execute(work, approvals=[approval(status="pending")]).outputs == {}
    rejected = execute(work, approvals=[approval(status="rejected")])
    assert rejected.state is WorkflowState.cancelled
    assert rejected.outputs == {}
    assert calls == []


def test_preflight_entire_plan_before_any_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(tools, "invoke_tool", lambda name, args: calls.append(name))
    work = plan(
        step("echo-1", requires_approval=False),
        step("save-1", "mock_save_note", requires_approval=False),
    )
    assert execute(work).state is WorkflowState.awaiting_approval
    assert execute(work, approvals=[approval("save-1", "rejected")]).state is (
        WorkflowState.cancelled
    )
    assert calls == []


def test_approved_tools_run_once_in_plan_order() -> None:
    work = plan(
        step("echo-1", requires_approval=False),
        step("save-1", "mock_save_note", requires_approval=False),
    )
    result = execute(work, approvals=[approval("save-1")])
    assert result.state is WorkflowState.succeeded
    assert result.outputs == {
        "echo-1": "hello",
        "save-1": "Mock note saved: hello",
    }


def test_echo_default_requires_matching_approval() -> None:
    work = plan(step())
    assert execute(work).state is WorkflowState.awaiting_approval
    assert execute(work, approvals=[approval()]).outputs == {"step-1": "hello"}


@pytest.mark.parametrize(
    "change",
    [
        {"session_id": "other"},
        {"plan_id": "other"},
        {"step_id": "other"},
    ],
)
def test_mismatched_approval_rejected_before_tools(
    change: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(tools, "invoke_tool", lambda name, args: calls.append(name))
    with pytest.raises(ValueError):
        execute(plan(step()), approvals=[approval(**change)])
    assert calls == []


def test_duplicate_approvals_rejected() -> None:
    with pytest.raises(ValueError):
        execute(plan(step()), approvals=[approval(), approval()])


@pytest.mark.parametrize("tool_name", ["shell", "browser", "", "save_note"])
def test_unknown_tools_rejected(tool_name: str) -> None:
    if tool_name == "":
        with pytest.raises(Exception):
            step(tool_name=tool_name)
    else:
        with pytest.raises(ValueError):
            execute(plan(step(tool_name=tool_name)))


@pytest.mark.parametrize("arguments", [{}, {"text": ""}, {"text": "hi", "path": "x"}])
def test_malformed_arguments_rejected(arguments: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        execute(plan(step(arguments=arguments)))


@pytest.mark.parametrize(
    "state", [WorkflowState.succeeded, WorkflowState.failed, WorkflowState.cancelled]
)
def test_terminal_plans_cannot_execute(state: WorkflowState) -> None:
    with pytest.raises(ValueError):
        execute(plan(step(), state=state), approvals=[approval()])


def test_running_plan_waits_as_paused_and_paused_can_resume() -> None:
    work = plan(step(), state=WorkflowState.running)
    assert execute(work).state is WorkflowState.paused
    work = plan(step(), state=WorkflowState.paused)
    assert execute(work, approvals=[approval()]).state is WorkflowState.succeeded


def test_tool_failure_is_safe_and_does_not_leak_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(name: str, args: dict[str, str]) -> str:
        raise RuntimeError("private-token")

    monkeypatch.setattr(tools, "invoke_tool", fail)
    result = execute(plan(step()), approvals=[approval()])
    assert result.state is WorkflowState.failed
    assert result.error is not None
    assert "private-token" not in result.model_dump_json()
