"""Transcription contracts as specified in contracts.md (W2 baseline)."""

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
    language: str = Field(default="en", min_length=1)
    is_final: bool = Field(default=True)

    @field_validator("sequence_id", "start_ms", "end_ms", mode="before")
    @classmethod
    def require_integer(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("sequence and timing fields must be integers")
        return value

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if self.end_ms < self.start_ms:
            raise ValueError(
                f"end_ms ({self.end_ms}) cannot be less than start_ms ({self.start_ms})"
            )
        return self


class TranscriptEvent(EventEnvelope[Union[TranscriptSegment, ErrorEnvelope]]):
    """Typed event envelope for transcript events."""

    producer: Literal["transcription"] = "transcription"
    event_type: Literal["transcript.segment", "transcript.error"] = "transcript.segment"
