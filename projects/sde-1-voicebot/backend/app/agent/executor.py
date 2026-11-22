"""Preflight an entire workflow before invoking any mock tool.

Week 2 adds dependency ordering, permission scopes, approval expiry with an
injected clock, safe audit events, per-step timeouts, bounded retries for
idempotent tools only, and cooperative cancellation. With no Week 2 options the
behavior is the same as Week 1: one in-memory run, no durable history.

Week 3 adds an optional ``WorkflowStore``: checkpoints let a failed run resume
without re-running completed steps, and an idempotency key returns the stored
final result instead of executing twice. ``on_audit`` streams each audit event
as it happens (progress for the UI), ``approval_source`` reads approval
decisions from the backend, and ``runtime`` selects mock or real tools.
"""

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, wait
from datetime import datetime
from threading import Thread
from time import monotonic
from typing import Literal

from app.agent import tools
from app.agent.approvals import ApprovalSource
from app.agent.checkpoint import WorkflowStore
from app.agent.errors import TransientToolError, WorkflowPolicyError
from app.agent.plan_validation import execution_order
from app.agent.state_machine import transition
from app.contracts.common import ErrorEnvelope, WorkflowState
from app.contracts.workflow import (
    ApprovalRequest,
    AuditEvent,
    AuditKind,
    WorkflowPlan,
    WorkflowResult,
    WorkflowStep,
)

Clock = Callable[[], datetime]
AuditListener = Callable[[AuditEvent], None]
ToolInvoker = Callable[[str, Mapping[str, str]], str]
StepStatus = Literal["ok", "timeout", "failed", "cancelled", "expired"]

_TERMINAL = {WorkflowState.succeeded, WorkflowState.failed, WorkflowState.cancelled}
_POLL_SECONDS = 0.02


class CancellationToken:
    """Set by the caller; also stops waiting for a tool that is running."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


class _StepCancelled(Exception):
    """Cancellation arrived while a tool was still running."""


class _Audit:
    def __init__(
        self, plan: WorkflowPlan, listener: AuditListener | None = None
    ) -> None:
        self._plan = plan
        self._listener = listener
        self.events: list[AuditEvent] = []

    def record(
        self,
        kind: AuditKind,
        *,
        step_id: str | None = None,
        approval_id: str | None = None,
        **details: str,
    ) -> None:
        event = AuditEvent(
            sequence=len(self.events),
            kind=kind,
            plan_id=self._plan.plan_id,
            session_id=self._plan.session_id,
            step_id=step_id,
            approval_id=approval_id,
            details_redacted=dict(details),
        )
        self.events.append(event)
        if self._listener is not None:
            try:
                self._listener(event)
            except Exception:  # noqa: BLE001 - a broken listener never stops a run
                pass


def _result(
    plan: WorkflowPlan,
    state: WorkflowState,
    audit: _Audit,
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
        audit_events=audit.events,
    )


def _match_approvals(
    plan: WorkflowPlan, approvals: Sequence[ApprovalRequest]
) -> dict[str, ApprovalRequest]:
    steps = {step.step_id for step in plan.steps}
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
    return approval_by_step


def _approval_expired(approval: ApprovalRequest | None, clock: Clock | None) -> bool:
    if approval is None or approval.expires_at is None or clock is None:
        return False
    return approval.expires_at <= clock()


def _cancel(
    plan: WorkflowPlan,
    current: WorkflowState,
    audit: _Audit,
    *,
    reason: str,
    outputs: dict[str, str] | None = None,
) -> WorkflowResult:
    audit.record("workflow_cancelled", reason=reason)
    return _result(
        plan, transition(current, WorkflowState.cancelled), audit, outputs=outputs
    )


def execute(
    plan: WorkflowPlan,
    *,
    approvals: Sequence[ApprovalRequest] = (),
    granted_scopes: frozenset[str] = tools.DEFAULT_MOCK_SCOPES,
    clock: Clock | None = None,
    step_timeout_ms: int | None = None,
    max_retries: int = 0,
    cancellation: CancellationToken | None = None,
    invoker: ToolInvoker | None = None,
    correlation_id: str = "workflow-mock",
    store: WorkflowStore | None = None,
    idempotency_key: str | None = None,
    on_audit: AuditListener | None = None,
    approval_source: ApprovalSource | None = None,
    runtime: tools.ToolRuntime | None = None,
) -> WorkflowResult:
    """Run a plan; see ``_execute_once`` for the policy rules.

    - ``store`` keeps checkpoints: a later call for the same plan skips steps
      that already succeeded (audited as ``step_restored``) and never calls
      their tools again.
    - ``idempotency_key`` (needs ``store``): a finished run's result is stored;
      repeating the key for the same plan returns it without running anything,
      and using it for a different plan is a ``WORKFLOW_IDEMPOTENCY_CONFLICT``.
    - ``approval_source`` reads approvals from the backend instead of passing
      ``approvals`` directly (not both).
    - ``runtime`` chooses the tools' data and side effects; mock by default.
    """
    if idempotency_key is not None:
        if store is None:
            raise ValueError("idempotency_key requires a store")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key must be a nonblank string")
        if not isinstance(plan, WorkflowPlan):
            raise TypeError("plan must be a WorkflowPlan")
        stored = store.result_for_key(idempotency_key, plan)
        if stored is not None:
            return stored
    if approval_source is not None:
        if approvals:
            raise ValueError("pass approvals or approval_source, not both")
        approvals = tuple(approval_source.approvals_for_plan(plan.plan_id))
    result = _execute_once(
        plan,
        approvals=approvals,
        granted_scopes=granted_scopes,
        clock=clock,
        step_timeout_ms=step_timeout_ms,
        max_retries=max_retries,
        cancellation=cancellation,
        invoker=invoker,
        correlation_id=correlation_id,
        store=store,
        on_audit=on_audit,
        runtime=runtime,
    )
    if store is not None and result.state in _TERMINAL:
        if result.state == WorkflowState.succeeded:
            store.clear_checkpoint(plan.plan_id)
        if idempotency_key is not None:
            store.save_result(idempotency_key, plan, result)
    return result


def _execute_once(
    plan: WorkflowPlan,
    *,
    approvals: Sequence[ApprovalRequest],
    granted_scopes: frozenset[str],
    clock: Clock | None,
    step_timeout_ms: int | None,
    max_retries: int,
    cancellation: CancellationToken | None,
    invoker: ToolInvoker | None,
    correlation_id: str,
    store: WorkflowStore | None,
    on_audit: AuditListener | None,
    runtime: tools.ToolRuntime | None,
) -> WorkflowResult:
    """Execute once only if every policy check and required approval passes.

    - Invalid plans (unknown tool, bad arguments, missing scope, missing
      dependency, cycle) raise ``WorkflowPolicyError`` before any tool runs.
    - A rejected or expired approval cancels the run with zero tool calls.
    - Expiry is checked again before every step and retry, so an approval that
      runs out mid-run stops the remaining work.
    - Retries apply only to idempotent tools and are bounded by ``max_retries``.
    - Timeouts need ``clock``. A step that passes ``step_timeout_ms`` counts as
      timed out and its output is discarded, even if the tool is still blocked.
      A timed-out tool cannot be killed; see ``_call_supervised``.
    - A consequential tool is never called a second time.

    Without a ``WorkflowStore`` there is no history: calling it again may run
    the same steps again.
    """
    if not isinstance(plan, WorkflowPlan):
        raise TypeError("plan must be a WorkflowPlan")
    if plan.state in _TERMINAL:
        raise ValueError("cannot execute a terminal workflow")
    if type(max_retries) is not int or max_retries < 0:
        raise ValueError("max_retries must be a nonnegative integer")
    if step_timeout_ms is not None:
        if type(step_timeout_ms) is not int or step_timeout_ms <= 0:
            raise ValueError("step_timeout_ms must be a positive integer")
        if clock is None:
            raise ValueError("step_timeout_ms requires an injected clock")
    if not isinstance(granted_scopes, frozenset):
        raise TypeError("granted_scopes must be a frozenset")

    # Preflight: nothing below may invoke a tool.
    ordered = execution_order(plan)
    allowed_hosts = (runtime or tools.MOCK_RUNTIME).allowed_hosts
    for step in ordered:
        tools.validate_tool_call(
            step.tool_name, step.arguments, allowed_hosts=allowed_hosts
        )
        tools.check_scope(step.tool_name, granted_scopes)
    completed = store.completed_steps(plan) if store is not None else {}

    approval_by_step = _match_approvals(plan, approvals)
    has_expiry = any(a.expires_at is not None for a in approval_by_step.values())
    if clock is None and has_expiry:
        raise ValueError("approval expiry requires an injected clock")
    now = clock() if clock is not None else None

    audit = _Audit(plan, on_audit)
    # A step restored from a checkpoint already ran with its approval.
    required = [
        step
        for step in ordered
        if step.step_id not in completed
        and (step.requires_approval or tools.TOOL_SPECS[step.tool_name].consequential)
    ]

    # Any supplied rejection or expired approval stops the whole plan (Week 1 rule).
    blocked = False
    for step in ordered:
        approval = approval_by_step.get(step.step_id)
        if approval is None or step.step_id in completed:
            continue
        if approval.status == "rejected":
            audit.record(
                "approval_rejected",
                step_id=step.step_id,
                approval_id=approval.approval_id,
            )
            blocked = True
        elif (
            approval.expires_at is not None
            and now is not None
            and approval.expires_at <= now
        ):
            audit.record(
                "approval_expired",
                step_id=step.step_id,
                approval_id=approval.approval_id,
            )
            blocked = True
    if blocked:
        return _cancel(plan, plan.state, audit, reason="approval_not_granted")

    if cancellation is not None and cancellation.cancelled:
        return _cancel(plan, plan.state, audit, reason="cancelled_before_start")

    missing = [
        step
        for step in required
        if approval_by_step.get(step.step_id) is None
        or approval_by_step[step.step_id].status != "approved"
    ]
    if missing:
        for step in missing:
            approval = approval_by_step.get(step.step_id)
            audit.record(
                "approval_missing",
                step_id=step.step_id,
                approval_id=approval.approval_id if approval else None,
            )
        if plan.state == WorkflowState.draft:
            target = transition(plan.state, WorkflowState.awaiting_approval)
        elif plan.state == WorkflowState.running:
            target = transition(plan.state, WorkflowState.paused)
        else:
            target = plan.state
        return _result(plan, target, audit)

    for step in required:
        audit.record(
            "approval_granted",
            step_id=step.step_id,
            approval_id=approval_by_step[step.step_id].approval_id,
        )

    running = (
        plan.state
        if plan.state == WorkflowState.running
        else transition(plan.state, WorkflowState.running)
    )
    outputs: dict[str, str] = {}
    for step in ordered:
        if step.step_id in completed:
            outputs[step.step_id] = completed[step.step_id]
            audit.record("step_restored", step_id=step.step_id, reason="checkpoint")
            continue
        if cancellation is not None and cancellation.cancelled:
            return _cancel(
                plan, running, audit, reason="cancelled_during_run", outputs=outputs
            )
        approval = approval_by_step.get(step.step_id)
        status: StepStatus
        output = ""
        if _approval_expired(approval, clock):
            status = "expired"
        else:
            status, output = _run_step(
                step,
                audit=audit,
                approval=approval,
                clock=clock,
                step_timeout_ms=step_timeout_ms,
                max_retries=max_retries,
                cancellation=cancellation,
                invoker=invoker if invoker is not None else _runtime_invoker(runtime),
            )
        if status == "ok":
            outputs[step.step_id] = output
            if store is not None:
                store.save_step(plan, step.step_id, output)
            continue
        if status == "cancelled":
            return _cancel(
                plan, running, audit, reason="cancelled_during_run", outputs=outputs
            )
        if status == "expired":
            audit.record(
                "approval_expired",
                step_id=step.step_id,
                approval_id=approval.approval_id if approval else None,
            )
            return _cancel(
                plan,
                running,
                audit,
                reason="approval_expired_during_run",
                outputs=outputs,
            )
        timed_out = status == "timeout"
        return _result(
            plan,
            transition(running, WorkflowState.failed),
            audit,
            outputs=outputs,
            error=ErrorEnvelope(
                code="WORKFLOW_STEP_TIMEOUT" if timed_out else "WORKFLOW_TOOL_FAILED",
                message_safe_for_user=(
                    "The mock workflow step timed out."
                    if timed_out
                    else "The mock workflow step failed."
                ),
                retryable=False,
                correlation_id=correlation_id,
                details_redacted={"step_id": step.step_id},
            ),
        )
    return _result(
        plan, transition(running, WorkflowState.succeeded), audit, outputs=outputs
    )


def _runtime_invoker(runtime: tools.ToolRuntime | None) -> ToolInvoker | None:
    # None keeps the Week 2 behaviour: ``tools.invoke_tool`` is looked up at call
    # time (mock runtime), which existing callers and tests rely on.
    return runtime.invoke if runtime is not None else None


def _call_supervised(
    call: ToolInvoker,
    tool_name: str,
    arguments: Mapping[str, str],
    timeout_ms: int | None,
    cancellation: CancellationToken | None,
) -> str:
    """Run a tool on a daemon thread; stop waiting at a deadline or on cancel.

    Raises ``TimeoutError`` at the deadline and ``_StepCancelled`` on cancel.
    Python cannot kill a thread, so a blocked tool keeps running in the
    background and any late result is ignored. The caller must treat that
    call's effect as unknown: that is why only idempotent tools are retried.
    """
    outcome: Future[str] = Future()

    def run() -> None:
        try:
            outcome.set_result(call(tool_name, arguments))
        except Exception as error:
            outcome.set_exception(error)

    Thread(target=run, name=f"workflow-{tool_name}", daemon=True).start()
    deadline = None if timeout_ms is None else monotonic() + timeout_ms / 1000
    while True:
        remaining = _POLL_SECONDS if deadline is None else deadline - monotonic()
        wait([outcome], timeout=max(0.0, min(_POLL_SECONDS, remaining)))
        if outcome.done():
            return outcome.result()
        if cancellation is not None and cancellation.cancelled:
            wait([outcome], timeout=_POLL_SECONDS)  # Keep a result landing now.
            if outcome.done():
                return outcome.result()
            raise _StepCancelled
        if deadline is not None and monotonic() >= deadline:
            raise TimeoutError


def _run_step(
    step: WorkflowStep,
    *,
    audit: _Audit,
    approval: ApprovalRequest | None,
    clock: Clock | None,
    step_timeout_ms: int | None,
    max_retries: int,
    cancellation: CancellationToken | None,
    invoker: ToolInvoker | None,
) -> tuple[StepStatus, str]:
    """Return ("ok", output) or (failure status, "")."""
    policy = tools.get_policy(step.tool_name)
    call = invoker if invoker is not None else tools.invoke_tool
    attempt = 0
    while True:
        attempt += 1
        started = clock() if clock is not None else None
        failure: str | None = None
        try:
            if step_timeout_ms is None and cancellation is None:
                output = call(step.tool_name, step.arguments)
            else:
                output = _call_supervised(
                    call,
                    step.tool_name,
                    step.arguments,
                    step_timeout_ms,
                    cancellation,
                )
        except _StepCancelled:
            return "cancelled", ""
        except TimeoutError:
            failure = "timeout"
        except TransientToolError:
            failure = "transient"
        except Exception:  # noqa: BLE001 - never expose tool exception text
            failure = "failed"

        if failure is None and started is not None and step_timeout_ms is not None:
            assert clock is not None
            elapsed_ms = (clock() - started).total_seconds() * 1000
            if elapsed_ms > step_timeout_ms:
                failure = "timeout"  # The late output is discarded.

        if failure is None:
            audit.record("step_succeeded", step_id=step.step_id, attempt=str(attempt))
            return "ok", output

        audit.record(
            "step_timed_out" if failure == "timeout" else "step_failed",
            step_id=step.step_id,
            attempt=str(attempt),
        )
        retryable = failure in {"timeout", "transient"} and policy.idempotent
        if not retryable or attempt > max_retries:
            return ("timeout" if failure == "timeout" else "failed"), ""
        if cancellation is not None and cancellation.cancelled:
            return "cancelled", ""
        if _approval_expired(approval, clock):
            return "expired", ""
        audit.record("step_retried", step_id=step.step_id, attempt=str(attempt + 1))


__all__ = ["CancellationToken", "WorkflowPolicyError", "execute"]
