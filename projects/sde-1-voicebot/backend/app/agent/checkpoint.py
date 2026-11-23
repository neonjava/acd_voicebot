"""In-memory checkpoints and idempotency records for workflow runs.

A checkpoint remembers which steps of a plan already succeeded and their
outputs, so resuming after a failure never runs a completed step again. An
idempotency key remembers the final result of a run, so sending the same
request twice never executes anything twice.

A checkpoint also remembers approval-gated steps whose outcome is unknown (a
timeout, or a cancel while the tool was still running) and the approval that
was used, so a resume asks for a fresh approval instead of repeating them.

Only ``succeeded`` and ``cancelled`` results are kept under an idempotency
key; a ``failed`` run is not, so the same key resumes from the checkpoint. A
key is reserved while its run is in progress: an overlapping call with the
same key is refused (``WORKFLOW_IDEMPOTENCY_IN_PROGRESS``).

Both are tied to a fingerprint of the plan (everything except its state): the
same plan ID with different steps is a conflict, not a resume. Records live in
this process only; they are not a durable database.
"""

import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock

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
    # step_id -> approval_id used by the attempt whose outcome is unknown.
    outcome_unknown: dict[str, str | None] = field(default_factory=dict)


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
        self._in_progress: set[str] = set()
        self._lock = Lock()

    def _trim(self, records: OrderedDict) -> None:  # type: ignore[type-arg]
        while len(records) > self._max_entries:
            records.popitem(last=False)

    def _existing(self, plan: WorkflowPlan) -> _Checkpoint | None:
        record = self._checkpoints.get(plan.plan_id)
        if record is not None and record.fingerprint != plan_fingerprint(plan):
            raise WorkflowPolicyError(
                "WORKFLOW_CHECKPOINT_CONFLICT",
                "a different plan already uses this plan ID",
            )
        return record

    def _writable(self, plan: WorkflowPlan) -> _Checkpoint:
        fingerprint = plan_fingerprint(plan)
        record = self._checkpoints.get(plan.plan_id)
        if record is None or record.fingerprint != fingerprint:
            record = _Checkpoint(fingerprint)
            self._checkpoints[plan.plan_id] = record
        self._checkpoints.move_to_end(plan.plan_id)
        self._trim(self._checkpoints)
        return record

    def completed_steps(self, plan: WorkflowPlan) -> dict[str, str]:
        """Outputs of steps that already succeeded for this exact plan."""
        record = self._existing(plan)
        return dict(record.completed) if record is not None else {}

    def outcome_unknown_steps(self, plan: WorkflowPlan) -> dict[str, str | None]:
        """Approval-gated steps whose last attempt may or may not have run.

        Maps each step ID to the approval ID that attempt used.
        """
        record = self._existing(plan)
        return dict(record.outcome_unknown) if record is not None else {}

    def save_step(self, plan: WorkflowPlan, step_id: str, output: str) -> None:
        record = self._writable(plan)
        record.completed[step_id] = output
        record.outcome_unknown.pop(step_id, None)

    def mark_outcome_unknown(
        self, plan: WorkflowPlan, step_id: str, approval_id: str | None
    ) -> None:
        """Remember that this step must not run again under ``approval_id``."""
        self._writable(plan).outcome_unknown[step_id] = approval_id

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

    def claim_key(self, key: str, plan: WorkflowPlan) -> WorkflowResult | None:
        """Return the stored result, or reserve the key for a new run.

        Atomic: of two overlapping calls with one key, only one gets ``None``
        (and must call ``release_key``); the other gets
        ``WORKFLOW_IDEMPOTENCY_IN_PROGRESS``.
        """
        with self._lock:
            stored = self.result_for_key(key, plan)
            if stored is not None:
                return stored
            if key in self._in_progress:
                raise WorkflowPolicyError(
                    "WORKFLOW_IDEMPOTENCY_IN_PROGRESS",
                    "a run with this idempotency key is still in progress",
                )
            self._in_progress.add(key)
            return None

    def release_key(self, key: str) -> None:
        with self._lock:
            self._in_progress.discard(key)

    def save_result(self, key: str, plan: WorkflowPlan, result: WorkflowResult) -> None:
        with self._lock:
            self._results[key] = _IdempotencyRecord(
                plan_fingerprint(plan), result.model_copy(deep=True)
            )
            self._results.move_to_end(key)
            self._trim(self._results)
