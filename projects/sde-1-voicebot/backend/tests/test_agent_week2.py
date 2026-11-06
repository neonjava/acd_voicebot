"""W4 Week 2 policy matrix: dependencies, scopes, expiry, timeouts, retries, cancel."""

import threading
from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.agent import tools
from app.agent.errors import TransientToolError, WorkflowPolicyError
from app.agent.executor import CancellationToken, execute
from app.agent.plan_validation import execution_order
from app.contracts.common import WorkflowState
from app.contracts.workflow import ApprovalRequest, WorkflowPlan, WorkflowStep

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
SECRET = "synthetic private note text"


class FakeClock:
    """Deterministic clock; each tool call can advance it."""

    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, ms: int) -> None:
        self.now += timedelta(milliseconds=ms)


def step(
    step_id: str,
    tool: str = "echo_text",
    *,
    text: str = "hello",
    depends_on: list[str] | None = None,
    requires_approval: bool = False,
) -> WorkflowStep:
    return WorkflowStep(
        step_id=step_id,
        tool_name=tool,
        arguments={"text": text},
        requires_approval=requires_approval,
        depends_on=depends_on or [],
    )


def plan(*steps: WorkflowStep) -> WorkflowPlan:
    return WorkflowPlan(plan_id="plan-1", session_id="session-1", steps=list(steps))


def approval(
    step_id: str,
    status: str = "approved",
    *,
    expires_at: datetime | None = None,
    approval_id: str | None = None,
) -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=approval_id or f"approval-{step_id}",
        plan_id="plan-1",
        session_id="session-1",
        step_id=step_id,
        status=status,
        expires_at=expires_at,
    )


class Recorder:
    def __init__(self, behaviors: list[object] | None = None) -> None:
        self.calls: list[str] = []
        self.behaviors = list(behaviors or [])

    def __call__(self, name: str, arguments: Mapping[str, str]) -> str:
        self.calls.append(name)
        if self.behaviors:
            behavior = self.behaviors.pop(0)
            if isinstance(behavior, BaseException):
                raise behavior
            if callable(behavior):
                behavior()
        return tools.invoke_tool(name, arguments)


# --- Dependencies and cycles -------------------------------------------------


def test_dependencies_set_execution_order_and_keep_plan_order_for_ties() -> None:
    work = plan(
        step("c", depends_on=["a", "b"]),
        step("a"),
        step("b", depends_on=["a"]),
        step("d"),
    )
    assert [s.step_id for s in execution_order(work)] == ["a", "d", "b", "c"]
    recorder = Recorder()
    result = execute(work, invoker=recorder)
    assert result.state is WorkflowState.succeeded
    assert list(result.outputs) == ["a", "d", "b", "c"]


def test_missing_dependency_is_rejected_before_any_tool() -> None:
    recorder = Recorder()
    with pytest.raises(WorkflowPolicyError) as caught:
        execute(plan(step("a", depends_on=["ghost"])), invoker=recorder)
    assert caught.value.code == "WORKFLOW_MISSING_DEPENDENCY"
    assert "ghost" in str(caught.value)
    assert recorder.calls == []


@pytest.mark.parametrize(
    "steps",
    [
        [step("a", depends_on=["b"]), step("b", depends_on=["a"])],
        [
            step("a", depends_on=["c"]),
            step("b", depends_on=["a"]),
            step("c", depends_on=["b"]),
        ],
        [step("ok"), step("x", depends_on=["y"]), step("y", depends_on=["x"])],
    ],
)
def test_cycles_are_rejected_before_any_tool(steps: list[WorkflowStep]) -> None:
    recorder = Recorder()
    with pytest.raises(WorkflowPolicyError) as caught:
        execute(plan(*steps), invoker=recorder)
    assert caught.value.code == "WORKFLOW_DEPENDENCY_CYCLE"
    assert recorder.calls == []


@pytest.mark.parametrize("deps", [["a"], ["b", "b"], [" "]])
def test_invalid_dependency_lists_fail_contract_validation(deps: list[str]) -> None:
    with pytest.raises(ValidationError):
        WorkflowStep(
            step_id="a", tool_name="echo_text", arguments={"text": "x"}, depends_on=deps
        )


# --- Tool registry, arguments and scopes -------------------------------------


@pytest.mark.parametrize(
    ("tool", "arguments", "code"),
    [
        ("shell", {"text": "ls"}, "WORKFLOW_UNKNOWN_TOOL"),
        ("echo_text", {}, "WORKFLOW_INVALID_ARGUMENTS"),
        ("echo_text", {"text": "x", "to": "y"}, "WORKFLOW_INVALID_ARGUMENTS"),
        ("echo_text", {"body": "x"}, "WORKFLOW_INVALID_ARGUMENTS"),
        ("echo_text", {"text": "   "}, "WORKFLOW_INVALID_ARGUMENTS"),
        (
            "echo_text",
            {"text": "x" * (tools.MAX_TEXT_LENGTH + 1)},
            "WORKFLOW_INVALID_ARGUMENTS",
        ),
    ],
)
def test_unknown_tools_and_bad_arguments_run_nothing(
    tool: str, arguments: dict[str, str], code: str
) -> None:
    recorder = Recorder()
    work = plan(
        step("first"),
        WorkflowStep(step_id="bad", tool_name=tool, arguments=arguments),
    )
    with pytest.raises(WorkflowPolicyError) as caught:
        execute(work, invoker=recorder)
    assert caught.value.code == code
    assert recorder.calls == []


def test_text_at_exact_length_limit_is_allowed() -> None:
    result = execute(plan(step("a", text="x" * tools.MAX_TEXT_LENGTH)))
    assert result.state is WorkflowState.succeeded


def test_missing_scope_is_denied_before_any_tool() -> None:
    recorder = Recorder()
    work = plan(step("echo"), step("save", "mock_save_note"))
    with pytest.raises(WorkflowPolicyError) as caught:
        execute(
            work,
            approvals=[approval("save")],
            granted_scopes=frozenset({"text:read"}),
            invoker=recorder,
        )
    assert caught.value.code == "WORKFLOW_SCOPE_DENIED"
    assert recorder.calls == []


def test_narrow_scope_allows_matching_tool() -> None:
    result = execute(plan(step("echo")), granted_scopes=frozenset({"text:read"}))
    assert result.state is WorkflowState.succeeded


def test_policy_error_converts_to_safe_envelope() -> None:
    envelope = WorkflowPolicyError("WORKFLOW_SCOPE_DENIED", "denied").to_envelope(
        "corr-1"
    )
    assert envelope.code == "WORKFLOW_SCOPE_DENIED"
    assert envelope.retryable is False
    assert envelope.correlation_id == "corr-1"


def test_registry_policy_is_fixed() -> None:
    assert tools.TOOL_POLICIES["echo_text"].idempotent is True
    assert tools.TOOL_POLICIES["mock_save_note"].idempotent is False
    assert set(tools.TOOL_POLICIES) == {"echo_text", "mock_save_note"}


# --- Approval, rejection and expiry ------------------------------------------


def test_rejected_approval_runs_zero_tools_and_audits_without_text() -> None:
    recorder = Recorder()
    work = plan(step("save", "mock_save_note", text=SECRET))
    result = execute(work, approvals=[approval("save", "rejected")], invoker=recorder)
    assert result.state is WorkflowState.cancelled
    assert recorder.calls == []
    kinds = [event.kind for event in result.audit_events]
    assert kinds == ["approval_rejected", "workflow_cancelled"]
    assert SECRET not in result.model_dump_json()


@pytest.mark.parametrize("offset_ms", [0, -1])
def test_expired_approval_runs_zero_tools(offset_ms: int) -> None:
    clock = FakeClock()
    recorder = Recorder()
    work = plan(step("save", "mock_save_note", text=SECRET))
    result = execute(
        work,
        approvals=[approval("save", expires_at=T0 + timedelta(milliseconds=offset_ms))],
        clock=clock,
        invoker=recorder,
    )
    assert result.state is WorkflowState.cancelled
    assert recorder.calls == []
    assert result.audit_events[0].kind == "approval_expired"
    assert result.audit_events[0].approval_id == "approval-save"
    assert SECRET not in result.model_dump_json()


def test_approval_valid_until_one_ms_before_expiry() -> None:
    clock = FakeClock()
    result = execute(
        plan(step("save", "mock_save_note")),
        approvals=[approval("save", expires_at=T0 + timedelta(milliseconds=1))],
        clock=clock,
    )
    assert result.state is WorkflowState.succeeded
    assert result.outputs == {"save": "Mock note saved: hello"}


def test_expiry_requires_injected_clock() -> None:
    with pytest.raises(ValueError, match="clock"):
        execute(
            plan(step("save", "mock_save_note")),
            approvals=[approval("save", expires_at=T0)],
        )


def test_naive_expiry_is_rejected_by_contract() -> None:
    with pytest.raises(ValidationError):
        approval("save", expires_at=datetime(2026, 1, 1))


def test_missing_approval_waits_and_audits_each_step() -> None:
    recorder = Recorder()
    work = plan(step("save", "mock_save_note"), step("echo", requires_approval=True))
    result = execute(work, invoker=recorder)
    assert result.state is WorkflowState.awaiting_approval
    assert recorder.calls == []
    assert [(e.kind, e.step_id) for e in result.audit_events] == [
        ("approval_missing", "save"),
        ("approval_missing", "echo"),
    ]


@pytest.mark.parametrize(
    "change", [{"session_id": "other"}, {"plan_id": "other"}, {"step_id": "ghost"}]
)
def test_mismatched_approval_ids_are_rejected(change: dict[str, str]) -> None:
    bad = approval("save").model_copy(update=change)
    with pytest.raises(ValueError, match="does not match"):
        execute(plan(step("save", "mock_save_note")), approvals=[bad])


def test_granted_run_records_ordered_audit_trail() -> None:
    result = execute(plan(step("save", "mock_save_note")), approvals=[approval("save")])
    assert [e.kind for e in result.audit_events] == [
        "approval_granted",
        "step_succeeded",
    ]
    assert [e.sequence for e in result.audit_events] == [0, 1]


# --- Timeouts and bounded retries -------------------------------------------


def test_idempotent_step_overrunning_timeout_is_retried_and_late_output_dropped() -> (
    None
):
    clock = FakeClock()
    recorder = Recorder([lambda: clock.advance(150)])
    result = execute(
        plan(step("echo")),
        clock=clock,
        step_timeout_ms=100,
        max_retries=1,
        invoker=recorder,
    )
    assert result.state is WorkflowState.succeeded
    assert recorder.calls == ["echo_text", "echo_text"]
    assert [e.kind for e in result.audit_events] == [
        "step_timed_out",
        "step_retried",
        "step_succeeded",
    ]


def test_step_finishing_exactly_at_timeout_is_accepted() -> None:
    clock = FakeClock()
    recorder = Recorder([lambda: clock.advance(100)])
    result = execute(
        plan(step("echo")), clock=clock, step_timeout_ms=100, invoker=recorder
    )
    assert result.state is WorkflowState.succeeded
    assert recorder.calls == ["echo_text"]


class BlockingTool:
    """Tool whose first ``block_calls`` calls hang until the test releases them."""

    def __init__(self, block_calls: int = 1) -> None:
        self.block_calls = block_calls
        self.calls: list[str] = []
        self.release = threading.Event()
        self.finished = threading.Event()

    def __call__(self, name: str, arguments: Mapping[str, str]) -> str:
        self.calls.append(name)
        if len(self.calls) <= self.block_calls:
            self.release.wait(timeout=2)  # Bounded so a regression cannot hang CI.
            self.finished.set()
        return tools.invoke_tool(name, arguments)


@pytest.fixture
def blocking_tool() -> Iterator[BlockingTool]:
    tool = BlockingTool()
    yield tool
    tool.release.set()


def test_blocked_tool_times_out_and_returns_control(
    blocking_tool: BlockingTool,
) -> None:
    result = execute(
        plan(step("echo")),
        clock=FakeClock(),
        step_timeout_ms=20,
        invoker=blocking_tool,
    )
    assert not blocking_tool.finished.is_set()  # The caller did not wait for it.
    assert result.state is WorkflowState.failed
    assert result.outputs == {}
    assert result.error is not None
    assert result.error.code == "WORKFLOW_STEP_TIMEOUT"
    assert [e.kind for e in result.audit_events] == ["step_timed_out"]


def test_blocked_idempotent_tool_is_retried_within_the_cap(
    blocking_tool: BlockingTool,
) -> None:
    result = execute(
        plan(step("echo")),
        clock=FakeClock(),
        step_timeout_ms=20,
        max_retries=1,
        invoker=blocking_tool,
    )
    assert not blocking_tool.finished.is_set()
    assert result.state is WorkflowState.succeeded
    assert result.outputs == {"echo": "hello"}
    assert blocking_tool.calls == ["echo_text", "echo_text"]


def test_blocked_consequential_tool_is_never_replayed(
    blocking_tool: BlockingTool,
) -> None:
    result = execute(
        plan(step("save", "mock_save_note", requires_approval=True)),
        approvals=[approval("save")],
        clock=FakeClock(),
        step_timeout_ms=20,
        max_retries=3,
        invoker=blocking_tool,
    )
    assert not blocking_tool.finished.is_set()
    assert result.state is WorkflowState.failed
    assert blocking_tool.calls == ["mock_save_note"]


def test_blocked_step_stops_later_steps(blocking_tool: BlockingTool) -> None:
    result = execute(
        plan(step("a"), step("b", depends_on=["a"])),
        clock=FakeClock(),
        step_timeout_ms=20,
        invoker=blocking_tool,
    )
    assert result.state is WorkflowState.failed
    assert blocking_tool.calls == ["echo_text"]


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        (TimeoutError(), "WORKFLOW_STEP_TIMEOUT"),
        (RuntimeError(SECRET), "WORKFLOW_TOOL_FAILED"),
    ],
)
def test_tool_errors_keep_their_meaning_under_a_deadline(
    raised: Exception, code: str
) -> None:
    result = execute(
        plan(step("echo")),
        clock=FakeClock(),
        step_timeout_ms=1000,
        invoker=Recorder([raised]),
    )
    assert result.error is not None
    assert result.error.code == code
    assert SECRET not in result.model_dump_json()


def test_tool_stays_on_the_calling_thread_without_a_timeout() -> None:
    seen: list[threading.Thread] = []

    def invoker(name: str, arguments: Mapping[str, str]) -> str:
        seen.append(threading.current_thread())
        return tools.invoke_tool(name, arguments)

    execute(plan(step("echo")), invoker=invoker)
    assert seen == [threading.current_thread()]


def test_retry_cap_bounds_attempts_and_fails_with_timeout_code() -> None:
    recorder = Recorder([TimeoutError(), TimeoutError(), TimeoutError()])
    result = execute(plan(step("echo")), max_retries=2, invoker=recorder)
    assert result.state is WorkflowState.failed
    assert len(recorder.calls) == 3
    assert result.error is not None
    assert result.error.code == "WORKFLOW_STEP_TIMEOUT"
    assert result.error.details_redacted == {"step_id": "echo"}


def test_consequential_tool_is_never_replayed() -> None:
    recorder = Recorder([TimeoutError()])
    result = execute(
        plan(step("save", "mock_save_note")),
        approvals=[approval("save")],
        max_retries=3,
        invoker=recorder,
    )
    assert result.state is WorkflowState.failed
    assert recorder.calls == ["mock_save_note"]
    assert "step_retried" not in [e.kind for e in result.audit_events]


def test_transient_error_is_retried_for_idempotent_tool() -> None:
    recorder = Recorder([TransientToolError("busy")])
    result = execute(plan(step("echo")), max_retries=1, invoker=recorder)
    assert result.state is WorkflowState.succeeded
    assert len(recorder.calls) == 2


def test_unexpected_error_is_not_retried_and_not_leaked() -> None:
    recorder = Recorder([RuntimeError("internal path /secret/token")])
    result = execute(plan(step("echo")), max_retries=3, invoker=recorder)
    assert result.state is WorkflowState.failed
    assert len(recorder.calls) == 1
    assert result.error is not None
    assert result.error.code == "WORKFLOW_TOOL_FAILED"
    assert "/secret/token" not in result.model_dump_json()


def test_failure_stops_later_steps_and_keeps_earlier_outputs() -> None:
    recorder = Recorder([None, RuntimeError("boom")])
    result = execute(
        plan(step("a"), step("b", depends_on=["a"]), step("c", depends_on=["b"])),
        invoker=recorder,
    )
    assert result.state is WorkflowState.failed
    assert result.outputs == {"a": "hello"}
    assert len(recorder.calls) == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_retries": -1},
        {"max_retries": True},
        {"step_timeout_ms": 0},
        {"step_timeout_ms": 100},  # no clock
        {"granted_scopes": {"text:read"}},
    ],
)
def test_invalid_executor_options_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises((ValueError, TypeError)):
        execute(plan(step("echo")), **kwargs)  # type: ignore[arg-type]


# --- Cancellation ------------------------------------------------------------


def test_cancelled_before_start_runs_zero_tools() -> None:
    token = CancellationToken()
    token.cancel()
    recorder = Recorder()
    result = execute(plan(step("echo")), cancellation=token, invoker=recorder)
    assert result.state is WorkflowState.cancelled
    assert recorder.calls == []
    assert result.audit_events[-1].details_redacted == {
        "reason": "cancelled_before_start"
    }


def test_cancel_during_run_stops_remaining_steps() -> None:
    token = CancellationToken()
    recorder = Recorder([token.cancel])
    result = execute(
        plan(step("a"), step("b"), step("c")), cancellation=token, invoker=recorder
    )
    assert result.state is WorkflowState.cancelled
    assert recorder.calls == ["echo_text"]
    assert result.outputs == {"a": "hello"}


def test_cancel_between_retries_stops_retrying() -> None:
    token = CancellationToken()

    def cancel_then_timeout() -> None:
        token.cancel()
        raise TimeoutError

    recorder = Recorder([cancel_then_timeout])
    result = execute(
        plan(step("echo")), max_retries=5, cancellation=token, invoker=recorder
    )
    assert result.state is WorkflowState.cancelled
    assert len(recorder.calls) == 1


def test_running_plan_can_be_cancelled_and_terminal_plan_is_refused() -> None:
    token = CancellationToken()
    token.cancel()
    running = plan(step("echo")).model_copy(update={"state": WorkflowState.running})
    assert execute(running, cancellation=token).state is WorkflowState.cancelled
    done = plan(step("echo")).model_copy(update={"state": WorkflowState.cancelled})
    with pytest.raises(ValueError, match="terminal"):
        execute(done)


# --- Published example for W5/W6 consumers -----------------------------------


def _fixture_result():  # noqa: ANN202 - test helper
    work = plan(step("echo"), step("save", "mock_save_note", depends_on=["echo"]))
    return execute(work, approvals=[approval("save", "rejected")])


def test_published_rejected_result_fixture_matches_executor() -> None:
    from pathlib import Path

    from app.contracts.workflow import WorkflowResult

    path = Path(__file__).parent / "fixtures" / "workflow" / "result_rejected.json"
    published = WorkflowResult.model_validate_json(path.read_text())
    assert published == _fixture_result()
