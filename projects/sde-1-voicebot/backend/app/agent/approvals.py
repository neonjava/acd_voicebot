"""Where the executor reads approval decisions from.

The backend (W5) owns approval state: the UI approves or rejects through its
approvals API. The executor only needs to read the current decisions for a
plan, so any object with ``approvals_for_plan`` works. ``InMemoryApprovalSource``
is the mock used by tests and demos; W5's session service provides the real
one after integration.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Literal, Protocol

from app.agent import tools
from app.agent.checkpoint import WorkflowStore
from app.agent.plan_validation import execution_order
from app.contracts.workflow import ApprovalRequest, WorkflowPlan


class ApprovalSource(Protocol):
    def approvals_for_plan(self, plan_id: str) -> Sequence[ApprovalRequest]: ...


class ApprovalDecisionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def steps_needing_approval(plan: WorkflowPlan) -> list[str]:
    """Step IDs that must be approved: the plan asks, or the tool is consequential."""
    return [
        step.step_id
        for step in execution_order(plan)
        if step.requires_approval or tools.get_policy(step.tool_name).spec.consequential
    ]


def _expiry(now: datetime, ttl_seconds: int) -> datetime:
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("now must be timezone-aware UTC")
    if type(ttl_seconds) is not int or ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be a positive integer")
    return now + timedelta(seconds=ttl_seconds)


def _pending(
    plan: WorkflowPlan, step_id: str, approval_id: str, expires_at: datetime
) -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=approval_id,
        plan_id=plan.plan_id,
        step_id=step_id,
        session_id=plan.session_id,
        status="pending",
        expires_at=expires_at,
    )


def approval_requests_for(
    plan: WorkflowPlan, *, now: datetime, ttl_seconds: int = 300
) -> list[ApprovalRequest]:
    """Pending requests (with expiry) for every step that needs approval."""
    expires_at = _expiry(now, ttl_seconds)
    return [
        _pending(plan, step_id, f"{plan.plan_id}-approval-{step_id}", expires_at)
        for step_id in steps_needing_approval(plan)
    ]


def reapproval_requests_for(
    plan: WorkflowPlan,
    store: WorkflowStore,
    *,
    now: datetime,
    ttl_seconds: int = 300,
) -> list[ApprovalRequest]:
    """Fresh pending requests for steps whose approval is already spent.

    An approval is spent once its step ran or may have run (outcome unknown);
    the executor then ignores it. To run such a step again the person must
    decide again, on a request with a new ID: ``{plan_id}-approval-{step_id}-N``
    with the lowest ``N >= 2`` that the step has not spent. The same call twice
    returns the same IDs, so registering them twice is ``APPROVAL_DUPLICATE``.
    Steps restored from the checkpoint need nothing.
    """
    expires_at = _expiry(now, ttl_seconds)
    spent = store.spent_approvals(plan.plan_id)
    completed = store.completed_steps(plan)
    requests: list[ApprovalRequest] = []
    for step_id in steps_needing_approval(plan):
        used = spent.get(step_id, frozenset())
        if not used or step_id in completed:
            continue
        attempt = len(used) + 1
        while f"{plan.plan_id}-approval-{step_id}-{attempt}" in used:
            attempt += 1
        approval_id = f"{plan.plan_id}-approval-{step_id}-{attempt}"
        requests.append(_pending(plan, step_id, approval_id, expires_at))
    return requests


class InMemoryApprovalSource:
    """Mock approval state: register requests, decide them once, read them back.

    Thread-safe: of two overlapping decisions on one request, only one is
    accepted; the other gets ``APPROVAL_ALREADY_DECIDED``.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, ApprovalRequest] = {}
        self._lock = Lock()

    def register(self, requests: Sequence[ApprovalRequest]) -> None:
        with self._lock:
            if len({r.approval_id for r in requests}) != len(requests) or any(
                r.approval_id in self._by_id for r in requests
            ):
                raise ApprovalDecisionError(
                    "APPROVAL_DUPLICATE", "approval request already exists"
                )
            for request in requests:
                self._by_id[request.approval_id] = request

    def decide(
        self,
        approval_id: str,
        decision: Literal["approve", "reject"],
        *,
        now: datetime | None = None,
    ) -> ApprovalRequest:
        """Approve or reject once; a second decision or an expired one is refused."""
        with self._lock:
            return self._decide(approval_id, decision, now)

    def _decide(
        self,
        approval_id: str,
        decision: Literal["approve", "reject"],
        now: datetime | None,
    ) -> ApprovalRequest:
        request = self._by_id.get(approval_id)
        if request is None:
            raise ApprovalDecisionError(
                "APPROVAL_NOT_FOUND", "approval request not found"
            )
        if request.status != "pending":
            raise ApprovalDecisionError(
                "APPROVAL_ALREADY_DECIDED", "approval request was already decided"
            )
        current = now or datetime.now(timezone.utc)
        if request.expires_at is not None and request.expires_at <= current:
            raise ApprovalDecisionError(
                "APPROVAL_EXPIRED", "approval request has expired"
            )
        if decision not in ("approve", "reject"):
            raise ApprovalDecisionError(
                "APPROVAL_INVALID", "decision must be approve or reject"
            )
        updated = request.model_copy(
            update={"status": "approved" if decision == "approve" else "rejected"}
        )
        self._by_id[approval_id] = updated
        return updated

    def approvals_for_plan(self, plan_id: str) -> list[ApprovalRequest]:
        with self._lock:
            return [a for a in self._by_id.values() if a.plan_id == plan_id]
