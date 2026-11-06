"""Workflow contracts owned by W4; no tool can act from a contract alone."""

from datetime import datetime, timezone
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from app.contracts.common import ContractModel, ErrorEnvelope, WorkflowState


class ToolSpec(ContractModel):
    name: str = Field(min_length=1, pattern=r"\S")
    description: str = Field(min_length=1, pattern=r"\S")
    consequential: bool

    @field_validator("consequential", mode="before")
    @classmethod
    def strict_consequential(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("consequential must be a boolean")
        return value


class WorkflowStep(ContractModel):
    step_id: str = Field(min_length=1, pattern=r"\S")
    tool_name: str = Field(min_length=1, pattern=r"\S")
    arguments: dict[str, str]
    requires_approval: bool = True
    depends_on: list[str] = Field(default_factory=list)

    @field_validator("requires_approval", mode="before")
    @classmethod
    def strict_approval_flag(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("requires_approval must be a boolean")
        return value

    @model_validator(mode="after")
    def valid_dependency_ids(self) -> Self:
        if any(not dep.strip() for dep in self.depends_on):
            raise ValueError("dependency IDs must be nonblank")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("dependency IDs must be unique per step")
        if self.step_id in self.depends_on:
            raise ValueError("a step cannot depend on itself")
        return self


class WorkflowPlan(ContractModel):
    plan_id: str = Field(min_length=1, pattern=r"\S")
    session_id: str = Field(min_length=1, pattern=r"\S")
    steps: list[WorkflowStep] = Field(min_length=1)
    state: WorkflowState = WorkflowState.draft

    @model_validator(mode="after")
    def unique_steps(self) -> Self:
        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step IDs must be unique")
        return self


class ApprovalRequest(ContractModel):
    approval_id: str = Field(min_length=1, pattern=r"\S")
    plan_id: str = Field(min_length=1, pattern=r"\S")
    step_id: str = Field(min_length=1, pattern=r"\S")
    session_id: str = Field(min_length=1, pattern=r"\S")
    status: Literal["pending", "approved", "rejected"] = "pending"
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def require_utc_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("expires_at must be timezone-aware UTC")
        return value


AuditKind = Literal[
    "approval_granted",
    "approval_rejected",
    "approval_expired",
    "approval_missing",
    "step_succeeded",
    "step_failed",
    "step_timed_out",
    "step_retried",
    "workflow_cancelled",
]


class AuditEvent(ContractModel):
    """Safe audit record. Never contains tool arguments, outputs or raw errors."""

    sequence: int = Field(ge=0, strict=True)
    kind: AuditKind
    plan_id: str = Field(min_length=1, pattern=r"\S")
    session_id: str = Field(min_length=1, pattern=r"\S")
    step_id: str | None = None
    approval_id: str | None = None
    details_redacted: dict[str, str] = Field(default_factory=dict)


class WorkflowResult(ContractModel):
    plan_id: str = Field(min_length=1, pattern=r"\S")
    session_id: str = Field(min_length=1, pattern=r"\S")
    state: WorkflowState
    outputs: dict[str, str] = Field(default_factory=dict)
    error: ErrorEnvelope | None = None
    audit_events: list[AuditEvent] = Field(default_factory=list)
