"""Week 1 workflow contracts; no tool can act from a contract alone."""

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

    @field_validator("requires_approval", mode="before")
    @classmethod
    def strict_approval_flag(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("requires_approval must be a boolean")
        return value


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


class WorkflowResult(ContractModel):
    plan_id: str = Field(min_length=1, pattern=r"\S")
    session_id: str = Field(min_length=1, pattern=r"\S")
    state: WorkflowState
    outputs: dict[str, str] = Field(default_factory=dict)
    error: ErrorEnvelope | None = None
