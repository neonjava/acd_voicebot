"""Common contracts and envelopes shared across all workstreams."""

from datetime import datetime, timezone
from enum import Enum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")


class ContractModel(BaseModel):
    """Base model forbidding unknown fields across all agreed interfaces."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SessionState(str, Enum):
    """Permitted session lifecycle states."""

    created = "created"
    active = "active"
    paused = "paused"
    stopping = "stopping"
    completed = "completed"
    failed = "failed"
    expired = "expired"


class WorkflowState(str, Enum):
    """Permitted workflow lifecycle states."""

    draft = "draft"
    awaiting_approval = "awaiting_approval"
    running = "running"
    paused = "paused"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class ErrorEnvelope(ContractModel):
    """Safe, typed error envelope returned by boundaries without leaking raw traces."""

    code: str = Field(min_length=1, pattern=r"\S")
    message_safe_for_user: str = Field(min_length=1)
    retryable: bool
    correlation_id: str = Field(min_length=1, pattern=r"\S")
    details_redacted: dict[str, str] = Field(default_factory=dict)

    @field_validator("retryable", mode="before")
    @classmethod
    def require_strict_boolean(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("retryable must be a strict boolean")
        return value


class EventEnvelope(ContractModel, Generic[T]):
    """Generic envelope wrapping all published domain events."""

    event_id: str = Field(min_length=1, pattern=r"\S")
    event_type: str = Field(min_length=1, pattern=r"\S")
    schema_version: Literal["1.0"] = "1.0"
    session_id: str = Field(min_length=1, pattern=r"\S")
    correlation_id: str = Field(min_length=1, pattern=r"\S")
    timestamp: datetime
    producer: str = Field(min_length=1, pattern=r"\S")
    payload: T

    @field_validator("timestamp")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware UTC")
        if value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("timestamp must have UTC offset (+00:00 or Z)")
        return value
