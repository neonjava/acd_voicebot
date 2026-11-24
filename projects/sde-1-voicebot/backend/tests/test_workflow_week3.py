"""Week 3 W4 (#68): checkpoint/resume, idempotency, audit progress, proposals,
backend approvals and the first real tools (system_stats, open_url)."""

import json
import subprocess
import sys
import threading
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

import pytest

from app.agent import tools
from app.agent.approvals import (
    ApprovalDecisionError,
    InMemoryApprovalSource,
    approval_requests_for,
    reapproval_requests_for,
    steps_needing_approval,
)
from app.agent.checkpoint import WorkflowStore
from app.agent.errors import TransientToolError, WorkflowPolicyError
from app.agent.executor import CancellationToken, execute
from app.agent.progress import audit_envelopes
from app.agent.proposals import plan_from_proposal
from app.agent.system_tools import (
    GIB,
    ProcessUsage,
    PsutilSystemStatsProvider,
    RecordingUrlOpener,
    SystemSnapshot,
    format_system_stats,
    friendly_process_name,
    top_processes,
)
from app.contracts.common import WorkflowState
from app.contracts.workflow import (
    ApprovalRequest,
    WorkflowPlan,
    WorkflowProposal,
    WorkflowStep,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def NOW() -> datetime:  # noqa: N802 - reads like a constant clock in calls
    return T0


SESSION = "session-w4"
CORRELATION = "corr-w4"


def step(
    step_id: str,
    tool: str = "echo_text",
    *,
    args: dict[str, str] | None = None,
    depends_on: tuple[str, ...] = (),
    requires_approval: bool = False,
) -> WorkflowStep:
    return WorkflowStep(
        step_id=step_id,
        tool_name=tool,
        arguments={"text": step_id} if args is None else args,
        requires_approval=requires_approval,
        depends_on=list(depends_on),
    )


def make_plan(*steps: WorkflowStep, plan_id: str = "plan-1") -> WorkflowPlan:
    return WorkflowPlan(plan_id=plan_id, session_id=SESSION, steps=list(steps))


def approved(plan: WorkflowPlan, step_id: str) -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=f"approval-{step_id}",
        plan_id=plan.plan_id,
        step_id=step_id,
        session_id=plan.session_id,
        status="approved",
    )


class Recorder:
    """Invoker that records calls and can fail chosen steps a set number of times."""

    def __init__(self, fail: Mapping[str, int] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._fail = dict(fail or {})

    def __call__(self, name: str, arguments: Mapping[str, str]) -> str:
        key = arguments.get("text", name)
        self.calls.append((name, key))
        if self._fail.get(key, 0) > 0:
            self._fail[key] -= 1
            raise RuntimeError("tool broke")
        return tools.invoke_tool(name, arguments)


# --- Checkpoint and resume ---------------------------------------------------


def test_resume_after_failure_skips_completed_steps_and_never_reruns_them() -> None:
    plan = make_plan(
        step("read"),
        step("save", "mock_save_note", depends_on=("read",)),
        step("report", depends_on=("save",)),
    )
    store = WorkflowStore()
    recorder = Recorder(fail={"report": 1})

    first = execute(
        plan, approvals=[approved(plan, "save")], store=store, invoker=recorder
    )
    assert first.state == WorkflowState.failed
    assert recorder.calls == [
        ("echo_text", "read"),
        ("mock_save_note", "save"),
        ("echo_text", "report"),
    ]

    # Resume: no approval is needed again for the saved step, and its
    # consequential tool is not called a second time.
    second = execute(plan, store=store, invoker=recorder)

    assert second.state == WorkflowState.succeeded
    assert recorder.calls[3:] == [("echo_text", "report")]
    assert second.outputs == {
        "read": "read",
        "save": "Mock note saved: save",
        "report": "report",
    }
    assert [(e.kind, e.step_id) for e in second.audit_events] == [
        ("step_restored", "read"),
        ("step_restored", "save"),
        ("step_succeeded", "report"),
    ]
    # A finished plan's checkpoint is cleared, so a fresh run starts over.
    assert store.completed_steps(plan) == {}


def test_checkpoint_for_a_different_plan_with_same_id_is_a_conflict() -> None:
    store = WorkflowStore()
    recorder = Recorder(fail={"b": 1})
    execute(make_plan(step("a"), step("b")), store=store, invoker=recorder)

    with pytest.raises(WorkflowPolicyError) as err:
        execute(make_plan(step("a"), step("c")), store=store, invoker=recorder)

    assert err.value.code == "WORKFLOW_CHECKPOINT_CONFLICT"
    assert recorder.calls == [("echo_text", "a"), ("echo_text", "b")]


# --- Idempotency keys ---------------------------------------------------------


def test_same_idempotency_key_returns_stored_result_without_running_again() -> None:
    plan = make_plan(step("save", "mock_save_note"))
    store = WorkflowStore()
    recorder = Recorder()
    kwargs = {"store": store, "idempotency_key": "key-1", "invoker": recorder}

    first = execute(plan, approvals=[approved(plan, "save")], **kwargs)
    second = execute(plan, approvals=[approved(plan, "save")], **kwargs)

    assert first.state == WorkflowState.succeeded
    assert second == first
    assert recorder.calls == [("mock_save_note", "save")]


def test_idempotency_key_reused_for_another_plan_is_rejected_before_any_tool() -> None:
    store = WorkflowStore()
    recorder = Recorder()
    execute(make_plan(step("a")), store=store, idempotency_key="k", invoker=recorder)

    with pytest.raises(WorkflowPolicyError) as err:
        execute(
            make_plan(step("b"), plan_id="plan-2"),
            store=store,
            idempotency_key="k",
            invoker=recorder,
        )
    assert err.value.code == "WORKFLOW_IDEMPOTENCY_CONFLICT"
    assert recorder.calls == [("echo_text", "a")]


def test_unfinished_run_is_not_stored_under_its_idempotency_key() -> None:
    plan = make_plan(step("save", "mock_save_note"))
    store = WorkflowStore()
    recorder = Recorder()

    waiting = execute(plan, store=store, idempotency_key="k", invoker=recorder)
    done = execute(
        plan,
        approvals=[approved(plan, "save")],
        store=store,
        idempotency_key="k",
        invoker=recorder,
    )

    assert waiting.state == WorkflowState.awaiting_approval
    assert done.state == WorkflowState.succeeded
    assert recorder.calls == [("mock_save_note", "save")]


def test_idempotency_key_requires_a_store() -> None:
    with pytest.raises(ValueError, match="requires a store"):
        execute(make_plan(step("a")), idempotency_key="k")


# --- Unknown outcomes, failed-run resume and concurrent keys (review of #81) ---


def _advancing_clock(seconds_per_call: float):  # noqa: ANN202 - test helper
    now = [T0]

    def clock() -> datetime:
        return now[0]

    def slow_tool(name: str, arguments: Mapping[str, str]) -> str:
        now[0] += timedelta(seconds=seconds_per_call)
        return tools.invoke_tool(name, arguments)

    return clock, slow_tool


def test_timed_out_consequential_step_needs_a_fresh_approval_to_run_again() -> None:
    plan = make_plan(step("save", "mock_save_note"))
    store = WorkflowStore()
    clock, slow_tool = _advancing_clock(5)
    recorder = Recorder()

    def late_save(name: str, arguments: Mapping[str, str]) -> str:
        recorder.calls.append((name, arguments["text"]))
        return slow_tool(name, arguments)  # returns after the 1 s deadline

    kwargs = {"store": store, "clock": clock, "step_timeout_ms": 1000}
    first = execute(
        plan, approvals=[approved(plan, "save")], invoker=late_save, **kwargs
    )
    assert first.state == WorkflowState.failed
    assert first.error is not None and first.error.code == "WORKFLOW_STEP_TIMEOUT"

    # The note may have been saved: the same approval must not save it again.
    again = execute(
        plan, approvals=[approved(plan, "save")], invoker=late_save, **kwargs
    )
    assert again.state == WorkflowState.awaiting_approval
    assert recorder.calls == [("mock_save_note", "save")]
    assert [
        (e.kind, e.step_id, e.approval_id, e.details_redacted)
        for e in again.audit_events
    ] == [
        (
            "approval_missing",
            "save",
            "approval-save",
            {"reason": "previous_outcome_unknown"},
        )
    ]

    # A fresh decision (new approval ID) lets the step run exactly once more.
    fresh = approved(plan, "save").model_copy(update={"approval_id": "approval-save-2"})
    done = execute(plan, approvals=[fresh], store=store, invoker=recorder)
    assert done.state == WorkflowState.succeeded
    assert recorder.calls == [("mock_save_note", "save"), ("mock_save_note", "save")]


def test_consequential_step_cancelled_mid_call_needs_a_fresh_approval() -> None:
    plan = make_plan(step("save", "mock_save_note"))
    store = WorkflowStore()
    token = CancellationToken()
    release = threading.Event()
    calls: list[str] = []

    def blocking_save(name: str, arguments: Mapping[str, str]) -> str:
        calls.append(name)
        token.cancel()
        release.wait(2)
        return tools.invoke_tool(name, arguments)

    try:
        first = execute(
            plan,
            approvals=[approved(plan, "save")],
            store=store,
            cancellation=token,
            invoker=blocking_save,
        )
    finally:
        release.set()
    assert first.state == WorkflowState.cancelled

    again = execute(
        plan, approvals=[approved(plan, "save")], store=store, invoker=blocking_save
    )
    assert again.state == WorkflowState.awaiting_approval
    assert calls == ["mock_save_note"]
    assert again.audit_events[-1].details_redacted == {
        "reason": "previous_outcome_unknown"
    }


def test_timed_out_safe_step_still_resumes_under_its_approval() -> None:
    # Only approval-gated steps need a fresh decision; a safe step just reruns.
    plan = make_plan(step("read"))
    store = WorkflowStore()
    clock, slow_tool = _advancing_clock(5)
    kwargs = {"store": store, "clock": clock, "step_timeout_ms": 1000}

    assert execute(plan, invoker=slow_tool, **kwargs).state == WorkflowState.failed
    assert execute(plan, store=store).state == WorkflowState.succeeded


def test_failed_run_with_an_idempotency_key_resumes_with_the_same_key() -> None:
    plan = make_plan(step("read"), step("save", "mock_save_note", depends_on=("read",)))
    store = WorkflowStore()
    recorder = Recorder(fail={"save": 1})
    kwargs = {
        "approvals": [approved(plan, "save")],
        "store": store,
        "idempotency_key": "retry-me",
        "invoker": recorder,
    }

    first = execute(plan, **kwargs)
    second = execute(plan, **kwargs)
    third = execute(plan, **kwargs)

    assert first.state == WorkflowState.failed
    assert second.state == WorkflowState.succeeded
    assert [(e.kind, e.step_id) for e in second.audit_events][:2] == [
        ("approval_granted", "save"),
        ("step_restored", "read"),
    ]
    assert third == second
    assert recorder.calls == [
        ("echo_text", "read"),
        ("mock_save_note", "save"),
        ("mock_save_note", "save"),
    ]


def test_concurrent_calls_with_one_idempotency_key_execute_once() -> None:
    plan = make_plan(step("save", "mock_save_note"))
    store = WorkflowStore()
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    results: list[WorkflowState] = []

    def blocking_save(name: str, arguments: Mapping[str, str]) -> str:
        calls.append(name)
        entered.set()
        release.wait(2)
        return tools.invoke_tool(name, arguments)

    kwargs = {
        "approvals": [approved(plan, "save")],
        "store": store,
        "idempotency_key": "double-click",
        "invoker": blocking_save,
    }
    worker = threading.Thread(
        target=lambda: results.append(execute(plan, **kwargs).state)
    )
    worker.start()
    try:
        assert entered.wait(2)
        with pytest.raises(WorkflowPolicyError) as err:
            execute(plan, **kwargs)
        assert err.value.code == "WORKFLOW_IDEMPOTENCY_IN_PROGRESS"
    finally:
        release.set()
        worker.join(2)

    assert results == [WorkflowState.succeeded]
    assert execute(plan, **kwargs).state == WorkflowState.succeeded
    assert calls == ["mock_save_note"]


# --- Spent approvals, overlapping runs and re-approval (review 2 of #81) -----


def test_every_used_approval_stays_used_after_several_unknown_outcomes() -> None:
    plan = make_plan(step("save", "mock_save_note"))
    store = WorkflowStore()
    clock, slow_tool = _advancing_clock(5)
    calls: list[str] = []

    def late_save(name: str, arguments: Mapping[str, str]) -> str:
        calls.append(name)
        return slow_tool(name, arguments)

    kwargs = {
        "store": store,
        "clock": clock,
        "step_timeout_ms": 1000,
        "invoker": late_save,
    }
    first = approved(plan, "save")
    second = first.model_copy(update={"approval_id": "approval-save-2"})
    assert execute(plan, approvals=[first], **kwargs).state == WorkflowState.failed
    assert execute(plan, approvals=[second], **kwargs).state == WorkflowState.failed

    # The first approval was spent by attempt 1; attempt 2 must not revive it.
    again = execute(plan, approvals=[first], **kwargs)
    assert again.state == WorkflowState.awaiting_approval
    assert calls == ["mock_save_note", "mock_save_note"]
    assert [
        (e.kind, e.approval_id, e.details_redacted) for e in again.audit_events
    ] == [("approval_missing", "approval-save", {"reason": "previous_outcome_unknown"})]


def test_an_approval_runs_its_step_once_even_after_the_plan_succeeded() -> None:
    plan = make_plan(step("read"), step("save", "mock_save_note"))
    source = backend_with_requests(plan)
    source.decide("plan-1-approval-save", "approve", now=T0)
    store = WorkflowStore()
    recorder = Recorder()
    kwargs = {"approval_source": source, "store": store, "clock": NOW}

    done = execute(plan, invoker=recorder, **kwargs)
    again = execute(plan, invoker=recorder, **kwargs)

    assert done.state == WorkflowState.succeeded
    assert again.state == WorkflowState.awaiting_approval
    assert recorder.calls == [("echo_text", "read"), ("mock_save_note", "save")]
    assert [
        (e.kind, e.step_id, e.approval_id, e.details_redacted)
        for e in again.audit_events
    ] == [
        (
            "approval_missing",
            "save",
            "plan-1-approval-save",
            {"reason": "approval_already_used"},
        )
    ]


def test_a_tool_failure_does_not_spend_the_approval() -> None:
    plan = make_plan(step("save", "mock_save_note"))
    store = WorkflowStore()
    recorder = Recorder(fail={"save": 1})
    kwargs = {"approvals": [approved(plan, "save")], "store": store}

    assert execute(plan, invoker=recorder, **kwargs).state == WorkflowState.failed
    assert execute(plan, invoker=recorder, **kwargs).state == WorkflowState.succeeded
    assert store.spent_approvals(plan.plan_id) == {"save": frozenset({"approval-save"})}


def test_overlapping_runs_of_one_plan_execute_once() -> None:
    plan = make_plan(step("save", "mock_save_note"))
    store = WorkflowStore()
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    results: list[WorkflowState] = []

    def blocking_save(name: str, arguments: Mapping[str, str]) -> str:
        calls.append(name)
        entered.set()
        release.wait(2)
        return tools.invoke_tool(name, arguments)

    kwargs = {
        "approvals": [approved(plan, "save")],
        "store": store,
        "invoker": blocking_save,
    }
    worker = threading.Thread(
        target=lambda: results.append(
            execute(plan, idempotency_key="tab-1", **kwargs).state
        )
    )
    worker.start()
    try:
        assert entered.wait(2)
        # No key, or another key: still the same plan, so it must not run again.
        for key in (None, "tab-2"):
            with pytest.raises(WorkflowPolicyError) as err:
                execute(plan, idempotency_key=key, **kwargs)
            assert err.value.code == "WORKFLOW_RUN_IN_PROGRESS"
    finally:
        release.set()
        worker.join(2)

    assert results == [WorkflowState.succeeded]
    assert calls == ["mock_save_note"]
    # The reservation is released: the next call runs (and finds nothing to do
    # without a fresh approval).
    assert execute(plan, **kwargs).state == WorkflowState.awaiting_approval
    assert calls == ["mock_save_note"]


def test_fresh_approval_through_the_backend_runs_the_step_again_once() -> None:
    plan = make_plan(step("save", "mock_save_note"))
    source = backend_with_requests(plan)
    source.decide("plan-1-approval-save", "approve", now=T0)
    store = WorkflowStore()
    clock, slow_tool = _advancing_clock(5)
    calls: list[str] = []

    def save(name: str, arguments: Mapping[str, str]) -> str:
        calls.append(name)
        return (slow_tool if len(calls) == 1 else tools.invoke_tool)(name, arguments)

    kwargs = {"approval_source": source, "store": store, "invoker": save}
    timed = execute(plan, clock=clock, step_timeout_ms=1000, **kwargs)
    assert timed.state == WorkflowState.failed
    assert execute(plan, clock=clock, **kwargs).state == (
        WorkflowState.awaiting_approval
    )

    fresh = reapproval_requests_for(plan, store, now=clock(), ttl_seconds=60)
    assert [(r.approval_id, r.step_id, r.status) for r in fresh] == [
        ("plan-1-approval-save-2", "save", "pending")
    ]
    source.register(fresh)
    with pytest.raises(ApprovalDecisionError) as err:
        source.register(reapproval_requests_for(plan, store, now=clock()))
    assert err.value.code == "APPROVAL_DUPLICATE"
    source.decide("plan-1-approval-save-2", "approve", now=clock())

    done = execute(plan, clock=clock, **kwargs)
    assert done.state == WorkflowState.succeeded
    assert calls == ["mock_save_note", "mock_save_note"]
    granted = [e.approval_id for e in done.audit_events if e.kind == "approval_granted"]
    assert granted == ["plan-1-approval-save-2"]
    # The fresh approval is spent too; the next request would be "-3".
    assert execute(plan, clock=clock, **kwargs).state == (
        WorkflowState.awaiting_approval
    )
    assert [r.approval_id for r in reapproval_requests_for(plan, store, now=T0)] == [
        "plan-1-approval-save-3"
    ]
    assert calls == ["mock_save_note", "mock_save_note"]


def test_reapproval_is_not_requested_for_unspent_or_restored_steps() -> None:
    plan = make_plan(
        step("save", "mock_save_note"),
        step("note", "mock_save_note", depends_on=("save",)),
        step("report", depends_on=("note",)),
    )
    store = WorkflowStore()
    recorder = Recorder(fail={"report": 1})
    approvals = [approved(plan, "save"), approved(plan, "note")]
    assert execute(plan, approvals=approvals, store=store, invoker=recorder).state == (
        WorkflowState.failed
    )
    # Both notes ran and are in the checkpoint: nothing to re-approve.
    assert reapproval_requests_for(plan, store, now=T0) == []
    assert (
        reapproval_requests_for(make_plan(step("x"), plan_id="p9"), store, now=T0) == []
    )


# --- Audit trail and progress events -------------------------------------------


def test_every_step_is_audited_live_and_published_as_workflow_audit_events() -> None:
    plan = make_plan(
        step("first", args={"text": "secret argument"}),
        step("second", depends_on=("first",)),
    )
    live: list[str] = []

    result = execute(plan, on_audit=lambda e: live.append(f"{e.kind}:{e.step_id}"))

    assert live == ["step_succeeded:first", "step_succeeded:second"]
    assert [f"{e.kind}:{e.step_id}" for e in result.audit_events] == live
    envelopes = audit_envelopes(
        result.audit_events, run_id="run-1", correlation_id=CORRELATION, timestamp=T0
    )
    assert [(e.event_type, e.producer, e.event_id) for e in envelopes] == [
        ("workflow.audit", "workflow", "plan-1-run-1-audit-0"),
        ("workflow.audit", "workflow", "plan-1-run-1-audit-1"),
    ]
    # Audit records never carry tool arguments or outputs.
    assert "secret argument" not in json.dumps(
        [e.model_dump(mode="json") for e in envelopes]
    )


def test_a_failing_audit_listener_never_stops_the_run() -> None:
    def broken(_event: object) -> None:
        raise RuntimeError("ui disconnected")

    result = execute(make_plan(step("a")), on_audit=broken)
    assert result.state == WorkflowState.succeeded


# --- Proposals from reasoning -----------------------------------------------------


def proposal(*steps: WorkflowStep) -> WorkflowProposal:
    return WorkflowProposal(
        proposal_id="proposal-1",
        session_id=SESSION,
        correlation_id=CORRELATION,
        summary="Check memory and open YouTube",
        steps=list(steps),
        source_ids=["transcript-0"],
    )


def test_valid_proposal_becomes_a_draft_plan_and_runs() -> None:
    plan = plan_from_proposal(
        proposal(
            step("stats", "system_stats", args={}),
            step("open", "open_url", args={"url": "https://www.youtube.com/"}),
        )
    )
    assert (plan.plan_id, plan.session_id, plan.state) == (
        "proposal-1",
        SESSION,
        WorkflowState.draft,
    )
    runtime = tools.ToolRuntime(opener=RecordingUrlOpener())
    result = execute(plan, runtime=runtime)

    assert result.state == WorkflowState.succeeded
    assert result.outputs["stats"].startswith("RAM 62% used")
    assert result.outputs["open"] == "Opened www.youtube.com"
    assert list(runtime.opener.opened) == ["https://www.youtube.com/"]


@pytest.mark.parametrize(
    ("bad_step", "code"),
    [
        (step("x", "delete_files", args={}), "WORKFLOW_UNKNOWN_TOOL"),
        (
            step("x", "open_url", args={"url": "https://evil.example"}),
            "WORKFLOW_URL_NOT_ALLOWED",
        ),
        (step("x", "system_stats", args={"pid": "1"}), "WORKFLOW_INVALID_ARGUMENTS"),
    ],
)
def test_invalid_proposals_are_rejected(bad_step: WorkflowStep, code: str) -> None:
    with pytest.raises(WorkflowPolicyError) as err:
        plan_from_proposal(proposal(bad_step))
    assert err.value.code == code


def test_proposal_cannot_skip_approval_for_a_consequential_tool() -> None:
    plan = plan_from_proposal(
        proposal(step("save", "mock_save_note", requires_approval=False))
    )
    recorder = Recorder()

    result = execute(plan, invoker=recorder)

    assert result.state == WorkflowState.awaiting_approval
    assert recorder.calls == []
    assert steps_needing_approval(plan) == ["save"]


# --- Approval state read from the backend ------------------------------------------


def backend_with_requests(plan: WorkflowPlan) -> InMemoryApprovalSource:
    source = InMemoryApprovalSource()
    source.register(approval_requests_for(plan, now=T0, ttl_seconds=60))
    return source


def test_backend_approval_then_execution_runs_the_step_once() -> None:
    plan = make_plan(step("read"), step("save", "mock_save_note"))
    source = backend_with_requests(plan)
    recorder = Recorder()

    assert [a.step_id for a in source.approvals_for_plan(plan.plan_id)] == ["save"]
    assert execute(plan, approval_source=source, invoker=recorder, clock=NOW).state == (
        WorkflowState.awaiting_approval
    )
    source.decide("plan-1-approval-save", "approve", now=T0)
    result = execute(plan, approval_source=source, invoker=recorder, clock=NOW)

    assert result.state == WorkflowState.succeeded
    assert recorder.calls == [("echo_text", "read"), ("mock_save_note", "save")]


def test_backend_rejection_never_executes_any_tool() -> None:
    plan = make_plan(step("read"), step("save", "mock_save_note"))
    source = backend_with_requests(plan)
    recorder = Recorder()

    source.decide("plan-1-approval-save", "reject", now=T0)
    result = execute(plan, approval_source=source, invoker=recorder, clock=NOW)

    assert result.state == WorkflowState.cancelled
    assert recorder.calls == []


def test_duplicate_decision_is_refused_and_does_not_run_the_tool_twice() -> None:
    plan = make_plan(step("save", "mock_save_note"))
    source = backend_with_requests(plan)
    store = WorkflowStore()
    recorder = Recorder()

    source.decide("plan-1-approval-save", "approve", now=T0)
    with pytest.raises(ApprovalDecisionError) as err:
        source.decide("plan-1-approval-save", "approve", now=T0)
    assert err.value.code == "APPROVAL_ALREADY_DECIDED"

    # The UI retries the same approved request: the idempotency key stops a rerun.
    for _ in range(2):
        execute(
            plan,
            approval_source=source,
            clock=NOW,
            store=store,
            idempotency_key="approve-save",
            invoker=recorder,
        )
    assert recorder.calls == [("mock_save_note", "save")]


def test_duplicate_approvals_for_one_step_never_execute() -> None:
    plan = make_plan(step("save", "mock_save_note"))
    source = InMemoryApprovalSource()
    first = approved(plan, "save")
    source.register([first, first.model_copy(update={"approval_id": "approval-2"})])
    recorder = Recorder()

    with pytest.raises(ValueError, match="duplicate workflow approval"):
        execute(plan, approval_source=source, invoker=recorder, clock=NOW)
    assert recorder.calls == []


def test_expired_approval_cannot_be_decided_and_never_executes() -> None:
    plan = make_plan(step("save", "mock_save_note"))
    source = backend_with_requests(plan)
    recorder = Recorder()
    later = T0 + timedelta(seconds=61)

    with pytest.raises(ApprovalDecisionError) as err:
        source.decide("plan-1-approval-save", "approve", now=later)
    assert err.value.code == "APPROVAL_EXPIRED"

    # Even if an approved-but-expired record reaches the executor, nothing runs.
    stale = approved(plan, "save").model_copy(update={"expires_at": T0})
    result = execute(plan, approvals=[stale], clock=lambda: later, invoker=recorder)
    assert result.state == WorkflowState.cancelled
    assert recorder.calls == []


class _SlowCopyRequest(ApprovalRequest):
    """Holds the first decision inside ``decide`` so a second one can overlap."""

    def model_copy(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        _DECIDING.set()
        _OVERLAP.wait(0.5)
        return super().model_copy(*args, **kwargs)


_DECIDING = threading.Event()
_OVERLAP = threading.Event()


def test_overlapping_approve_and_reject_accept_only_one_decision() -> None:
    _DECIDING.clear()
    _OVERLAP.clear()
    source = InMemoryApprovalSource()
    source.register(
        [
            _SlowCopyRequest(
                approval_id="a", plan_id="plan-1", step_id="save", session_id=SESSION
            )
        ]
    )
    accepted: list[str] = []
    refused: list[str] = []

    def decide(decision: str) -> None:
        try:
            source.decide("a", decision, now=T0)  # type: ignore[arg-type]
            accepted.append(decision)
        except ApprovalDecisionError as err:
            refused.append(err.code)

    approve = threading.Thread(target=decide, args=("approve",))
    approve.start()
    assert _DECIDING.wait(2)
    reject = threading.Thread(target=decide, args=("reject",))
    reject.start()
    reject.join(0.2)
    _OVERLAP.set()
    approve.join(2)
    reject.join(2)

    # The UI that rejected must never be told "rejected" while the step runs.
    assert accepted == ["approve"]
    assert refused == ["APPROVAL_ALREADY_DECIDED"]
    assert [a.status for a in source.approvals_for_plan("plan-1")] == ["approved"]


def test_approval_source_and_direct_approvals_are_exclusive() -> None:
    plan = make_plan(step("save", "mock_save_note"))
    with pytest.raises(ValueError, match="not both"):
        execute(
            plan,
            approvals=[approved(plan, "save")],
            approval_source=InMemoryApprovalSource(),
        )


# --- system_stats -------------------------------------------------------------------


def test_top_processes_groups_by_name_and_ranks_by_memory() -> None:
    processes = (
        ProcessUsage("code", 2 * GIB),
        ProcessUsage("chrome", int(1.5 * GIB)),
        ProcessUsage("chrome", int(1.0 * GIB)),
        ProcessUsage("python", GIB // 2),
    )
    assert top_processes(processes, limit=2) == [
        ProcessUsage("chrome", int(2.5 * GIB)),
        ProcessUsage("code", 2 * GIB),
    ]


def test_system_stats_summary_answers_whats_using_the_most_ram() -> None:
    snapshot = SystemSnapshot(
        ram_total_bytes=16 * GIB,
        ram_used_bytes=12 * GIB,
        cpu_percent=37.4,
        processes=(ProcessUsage("chrome", int(3.1 * GIB)), ProcessUsage("code", GIB)),
    )
    assert format_system_stats(snapshot) == (
        "RAM 75% used (12.0 of 16.0 GB), CPU 37%. "
        "Top memory: chrome 3.1 GB, code 1.0 GB."
    )


def test_system_stats_without_psutil_gives_a_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "psutil", None)
    with pytest.raises(WorkflowPolicyError) as err:
        PsutilSystemStatsProvider().snapshot()
    assert err.value.code == "WORKFLOW_TOOL_UNAVAILABLE"


def test_agent_package_imports_without_the_system_extra() -> None:
    code = (
        "import sys\n"
        "sys.modules['psutil'] = None\n"
        "import app.agent.executor, app.agent.tools\n"
        "print(tools_ok := 'ok')\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "ok"


# --- open_url ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://www.youtube.com/",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://evil.example/",
        "https://youtube.com.evil.example/",
        "https://user:pw@youtube.com/",
        "https://you tube.com/",
    ],
)
def test_open_url_rejects_non_allow_listed_links_without_opening(url: str) -> None:
    runtime = tools.ToolRuntime(opener=RecordingUrlOpener())
    with pytest.raises(WorkflowPolicyError):
        runtime.invoke("open_url", {"url": url})
    assert list(runtime.opener.opened) == []


@pytest.mark.parametrize(
    "url",
    [
        # Browsers read "\" as "/" in https links, so this opens evil.example.
        "https://evil.example\\.youtube.com/",
        "https://evil.example\\@www.youtube.com/",
        "https://www.youtube.com\\..evil.example/",
        # Characters that are never part of a real host name.
        "https://evil.example%2f.youtube.com/",
        "https://evil.example;.youtube.com/",
        "https://evil_example.youtube.com/",
    ],
)
def test_open_url_rejects_hosts_a_browser_would_read_differently(url: str) -> None:
    runtime = tools.ToolRuntime(opener=RecordingUrlOpener())
    with pytest.raises(WorkflowPolicyError) as err:
        runtime.invoke("open_url", {"url": url})
    assert err.value.code == "WORKFLOW_URL_NOT_ALLOWED"
    assert list(runtime.opener.opened) == []


@pytest.mark.parametrize(
    "url", ["https://[youtube.com/", "https://youtube.com\uff0f@evil.example/"]
)
def test_open_url_rejects_links_python_cannot_parse(url: str) -> None:
    runtime = tools.ToolRuntime()
    with pytest.raises(WorkflowPolicyError) as err:
        runtime.invoke("open_url", {"url": url})
    assert err.value.code == "WORKFLOW_URL_NOT_ALLOWED"
    assert list(runtime.opener.opened) == []  # type: ignore[attr-defined]


def test_open_url_still_opens_allow_listed_url_with_port_and_path() -> None:
    runtime = tools.ToolRuntime(opener=RecordingUrlOpener())
    url = "https://GitHub.com:443/neonjava/acd_voicebot?tab=readme#top"
    assert runtime.invoke("open_url", {"url": url}) == "Opened github.com"
    assert list(runtime.opener.opened) == [url]


def test_open_url_opens_exact_allow_listed_url() -> None:
    runtime = tools.ToolRuntime(opener=RecordingUrlOpener())
    url = "https://www.youtube.com/results?search_query=avengers+trailer"
    assert runtime.invoke("open_url", {"url": url}) == "Opened www.youtube.com"
    assert list(runtime.opener.opened) == [url]


def test_executor_rejects_a_disallowed_url_before_running_any_step() -> None:
    plan = make_plan(
        step("read"),
        step("open", "open_url", args={"url": "https://evil.example/"}),
    )
    recorder = Recorder()
    with pytest.raises(WorkflowPolicyError) as err:
        execute(plan, invoker=recorder)
    assert err.value.code == "WORKFLOW_URL_NOT_ALLOWED"
    assert recorder.calls == []


def test_open_url_is_never_retried_because_it_is_not_idempotent() -> None:
    class FlakyOpener:
        def __init__(self) -> None:
            self.attempts = 0

        def open(self, url: str) -> None:
            self.attempts += 1
            raise TransientToolError("browser busy")

    opener = FlakyOpener()
    runtime = tools.ToolRuntime(opener=opener)
    plan = make_plan(step("open", "open_url", args={"url": "https://github.com/"}))

    result = execute(plan, runtime=runtime, max_retries=3)

    assert result.state == WorkflowState.failed
    assert opener.attempts == 1


def test_default_mock_mode_never_opens_a_real_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import webbrowser

    def refuse(*_args: object, **_kwargs: object) -> bool:
        raise AssertionError("a real browser was opened in mock mode")

    monkeypatch.setattr(webbrowser, "open_new_tab", refuse)
    plan = make_plan(step("open", "open_url", args={"url": "https://github.com/"}))
    assert execute(plan).state == WorkflowState.succeeded


@pytest.mark.parametrize(
    ("env", "mode", "hosts"),
    [
        ({}, "mock", tools.DEFAULT_ALLOWED_HOSTS),
        ({"WORKFLOW_TOOLS_MODE": "real"}, "real", tools.DEFAULT_ALLOWED_HOSTS),
        (
            {"WORKFLOW_ALLOWED_HOSTS": " YouTube.com , docs.python.org "},
            "mock",
            frozenset({"youtube.com", "docs.python.org"}),
        ),
    ],
)
def test_runtime_from_env(
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    mode: str,
    hosts: frozenset[str],
) -> None:
    monkeypatch.delenv("WORKFLOW_TOOLS_MODE", raising=False)
    monkeypatch.delenv("WORKFLOW_ALLOWED_HOSTS", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    runtime = tools.runtime_from_env()
    assert (runtime.mode, runtime.allowed_hosts) == (mode, hosts)


@pytest.mark.parametrize(
    "env",
    [{"WORKFLOW_TOOLS_MODE": "chaos"}, {"WORKFLOW_ALLOWED_HOSTS": " , "}],
)
def test_runtime_from_env_rejects_bad_config(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        tools.runtime_from_env()


@pytest.mark.parametrize(
    ("name", "exe", "expected"),
    [
        ("Isolated Web Co", "/opt/zen/zen-bin", "zen"),
        (
            "chrome.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "chrome",
        ),
        ("claude", "/home/u/.local/share/claude/versions/2.1.330", "claude"),
        ("code", None, "code"),
        ("python3.12", "", "python3.12"),
        (None, None, "unknown"),
    ],
)
def test_friendly_process_name_uses_the_program_file(
    name: str | None, exe: str | None, expected: str
) -> None:
    assert friendly_process_name(name, exe) == expected


def test_week3_demo_runs_in_mock_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.agent import week3_demo

    monkeypatch.delenv("WORKFLOW_TOOLS_MODE", raising=False)
    monkeypatch.delenv("WORKFLOW_ALLOWED_HOSTS", raising=False)
    assert week3_demo.main() == 0
    out = capsys.readouterr().out
    assert "mode=mock" in out
    assert "before approval: awaiting_approval" in out
    assert "after approval: succeeded" in out
    assert "same idempotency key again: succeeded" in out
    assert "resume: first=failed second=succeeded" in out
    assert "restored from checkpoint: ['stats']" in out
