"""Transcription contracts as specified in contracts.md (W2 baseline)."""

import math
from typing import Literal, Self, Union

from pydantic import Field, field_validator, model_validator

from app.contracts.common import ContractModel, ErrorEnvelope, EventEnvelope


class TranscriptSegment(ContractModel):
    """A recognized or mock transcript segment."""

    segment_id: str = Field(min_length=1, pattern=r"\S")
    session_id: str = Field(min_length=1, pattern=r"\S")
    sequence_id: int = Field(strict=True, ge=0)
    start_ms: int = Field(strict=True, ge=0)
    end_ms: int = Field(strict=True, ge=0)
    text: str = Field(min_length=1, pattern=r"\S")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    language: str = Field(default="en", min_length=1, pattern=r"\S")
    is_final: bool = Field(default=True)

    @field_validator("sequence_id", "start_ms", "end_ms", mode="before")
    @classmethod
    def require_integer(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("sequence and timing fields must be strict integers")
        return value

    @field_validator("is_final", mode="before")
    @classmethod
    def require_strict_boolean(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("is_final must be a strict boolean")
        return value

    @field_validator("confidence")
    @classmethod
    def require_finite_confidence(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("confidence must be a finite float")
        return value

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if self.end_ms < self.start_ms:
            raise ValueError(
                f"end_ms ({self.end_ms}) cannot be less than start_ms ({self.start_ms})"
            )
        return self


class TranscriptEvent(EventEnvelope[Union[TranscriptSegment, ErrorEnvelope]]):
    """Typed event envelope for transcript events with strict pairing validation."""

    producer: Literal["transcription"] = "transcription"
    event_type: Literal["transcript.segment", "transcript.error"] = "transcript.segment"

    @model_validator(mode="after")
    def validate_pairing_and_identifiers(self) -> Self:
        if self.event_type == "transcript.segment":
            if not isinstance(self.payload, TranscriptSegment):
                raise ValueError(
                    "payload must be TranscriptSegment for 'transcript.segment'"
                )
            if self.payload.session_id != self.session_id:
                raise ValueError(
                    f"payload session_id ({self.payload.session_id}) must match "
                    f"envelope session_id ({self.session_id})"
                )
        elif self.event_type == "transcript.error":
            if not isinstance(self.payload, ErrorEnvelope):
                raise ValueError("payload must be ErrorEnvelope for 'transcript.error'")
            if self.payload.correlation_id != self.correlation_id:
                raise ValueError(
                    f"payload correlation_id ({self.payload.correlation_id}) must "
                    f"match envelope correlation_id ({self.correlation_id})"
                )
        return self
