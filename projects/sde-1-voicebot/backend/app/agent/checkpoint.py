"""In-memory checkpoints and idempotency records for workflow runs.

A checkpoint remembers which steps of a plan already succeeded and their
outputs, so resuming after a failure never runs a completed step again. An
idempotency key remembers the final result of a run, so sending the same
request twice never executes anything twice.

Both are tied to a fingerprint of the plan (everything except its state): the
same plan ID with different steps is a conflict, not a resume. Records live in
this process only; they are not a durable database.
"""

import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field

from app.agent.errors import WorkflowPolicyError
from app.contracts.workflow import WorkflowPlan, WorkflowResult


def plan_fingerprint(plan: WorkflowPlan) -> str:
    """Stable hash of a plan's identity and steps (its state is ignored)."""
    payload = plan.model_dump_json(exclude={"state"})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class _Checkpoint:
    fingerprint: str
    completed: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _IdempotencyRecord:
    fingerprint: str
    result: WorkflowResult


class WorkflowStore:
    """Bounded in-memory store; the oldest plans are dropped first."""

    def __init__(self, *, max_entries: int = 1000) -> None:
        if type(max_entries) is not int or max_entries <= 0:
            raise ValueError("max_entries must be a positive integer")
        self._max_entries = max_entries
        self._checkpoints: OrderedDict[str, _Checkpoint] = OrderedDict()
        self._results: OrderedDict[str, _IdempotencyRecord] = OrderedDict()

    def _trim(self, records: OrderedDict) -> None:  # type: ignore[type-arg]
        while len(records) > self._max_entries:
            records.popitem(last=False)

    def completed_steps(self, plan: WorkflowPlan) -> dict[str, str]:
        """Outputs of steps that already succeeded for this exact plan."""
        record = self._checkpoints.get(plan.plan_id)
        if record is None:
            return {}
        if record.fingerprint != plan_fingerprint(plan):
            raise WorkflowPolicyError(
                "WORKFLOW_CHECKPOINT_CONFLICT",
                "a different plan already uses this plan ID",
            )
        return dict(record.completed)

    def save_step(self, plan: WorkflowPlan, step_id: str, output: str) -> None:
        fingerprint = plan_fingerprint(plan)
        record = self._checkpoints.get(plan.plan_id)
        if record is None or record.fingerprint != fingerprint:
            record = _Checkpoint(fingerprint)
            self._checkpoints[plan.plan_id] = record
        record.completed[step_id] = output
        self._checkpoints.move_to_end(plan.plan_id)
        self._trim(self._checkpoints)

    def clear_checkpoint(self, plan_id: str) -> None:
        self._checkpoints.pop(plan_id, None)

    def result_for_key(self, key: str, plan: WorkflowPlan) -> WorkflowResult | None:
        """The stored final result for this key, or a conflict for another plan."""
        record = self._results.get(key)
        if record is None:
            return None
        if record.fingerprint != plan_fingerprint(plan):
            raise WorkflowPolicyError(
                "WORKFLOW_IDEMPOTENCY_CONFLICT",
                "this idempotency key was already used for a different plan",
            )
        return record.result.model_copy(deep=True)

    def save_result(self, key: str, plan: WorkflowPlan, result: WorkflowResult) -> None:
        self._results[key] = _IdempotencyRecord(
            plan_fingerprint(plan), result.model_copy(deep=True)
        )
        self._results.move_to_end(key)
        self._trim(self._results)
