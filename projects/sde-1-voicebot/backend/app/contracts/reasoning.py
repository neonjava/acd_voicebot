"""Context and reasoning contracts owned by W3."""

from datetime import datetime, timezone
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from app.contracts.common import ContractModel, ErrorEnvelope


class SourceReference(ContractModel):
    """An identified source of synthetic screen or transcript context."""

    source_id: str = Field(min_length=1, pattern=r"\S")
    locator: str = Field(min_length=1, pattern=r"\S")
    kind: Literal["synthetic_screen", "transcript"]


class ContextItem(ContractModel):
    """Untrusted evidence text with its source kept separate."""

    item_id: str = Field(min_length=1, pattern=r"\S")
    text: str = Field(min_length=1, pattern=r"\S")
    source: SourceReference


class ScreenContext(ContractModel):
    """A synthetic frame; capture_enabled is permission for future real capture."""

    frame_id: str = Field(min_length=1, pattern=r"\S")
    captured_at: datetime
    capture_enabled: bool = False
    items: list[ContextItem] = Field(default_factory=list)

    @field_validator("captured_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("captured_at must be timezone-aware UTC")
        return value

    @field_validator("capture_enabled", mode="before")
    @classmethod
    def require_boolean(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("capture_enabled must be a boolean")
        return value


class ReasoningRequest(ContractModel):
    """A question and its supplied, untrusted context."""

    request_id: str = Field(min_length=1, pattern=r"\S")
    session_id: str = Field(min_length=1, pattern=r"\S")
    question: str = Field(min_length=1, pattern=r"\S")
    context: list[ContextItem] = Field(default_factory=list)
    prompt_version: Literal["v1"] = "v1"


class ReasoningResult(ContractModel):
    """Deterministic mock answer and the IDs of evidence used."""

    request_id: str = Field(min_length=1, pattern=r"\S")
    session_id: str = Field(min_length=1, pattern=r"\S")
    answer: str = Field(min_length=1, pattern=r"\S")
    source_ids: list[str] = Field(default_factory=list)
    insufficient_evidence: bool
    prompt_version: Literal["v1"] = "v1"

    @field_validator("insufficient_evidence", mode="before")
    @classmethod
    def require_boolean(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("insufficient_evidence must be a boolean")
        return value

    @field_validator("source_ids")
    @classmethod
    def require_source_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("source_ids must be nonblank")
        if len(values) != len(set(values)):
            raise ValueError("source_ids must be unique")
        return values

    @model_validator(mode="after")
    def require_consistent_evidence(self) -> Self:
        if self.insufficient_evidence and self.source_ids:
            raise ValueError("insufficient evidence cannot cite sources")
        if not self.insufficient_evidence and not self.source_ids:
            raise ValueError("a grounded result must cite a source")
        return self


class CaptureSettings(ContractModel):
    """Opt-in screen-context capture settings. Capture is off unless enabled."""

    enabled: bool = False
    sampling_interval_ms: int = Field(default=2000, ge=500, le=60_000, strict=True)
    max_frame_bytes: int = Field(default=2_000_000, gt=0, le=10_000_000, strict=True)
    max_width: int = Field(default=1920, gt=0, le=7680, strict=True)
    max_height: int = Field(default=1080, gt=0, le=4320, strict=True)

    @field_validator("enabled", mode="before")
    @classmethod
    def require_boolean(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("enabled must be a boolean")
        return value


class ReasoningOutcome(ContractModel):
    """Either a validated result or a safe error, never both."""

    request_id: str = Field(min_length=1, pattern=r"\S")
    session_id: str = Field(min_length=1, pattern=r"\S")
    result: ReasoningResult | None = None
    error: ErrorEnvelope | None = None
    attempts: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def exactly_one(self) -> Self:
        if (self.result is None) == (self.error is None):
            raise ValueError("outcome needs exactly one of result or error")
        if self.result is not None and (
            self.result.request_id != self.request_id
            or self.result.session_id != self.session_id
        ):
            raise ValueError("result must match the outcome request and session")
        return self
