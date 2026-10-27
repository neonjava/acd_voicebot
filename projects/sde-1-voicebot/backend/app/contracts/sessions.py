"""Session contracts and wire projections owned by W5 (Backend)."""

from typing import Any, Literal

from pydantic import Field, field_validator

from app.contracts.common import ContractModel, EventEnvelope


class AudioChunkMetadata(ContractModel):
    """Wire projection of audio chunks exposed to clients (no raw PCM)."""

    sequence_id: int = Field(strict=True, ge=0)
    start_ms: int = Field(strict=True, ge=0)
    duration_ms: int = Field(strict=True, gt=0)
    sample_rate_hz: Literal[16000] = 16000
    channels: Literal[1] = 1
    size_bytes: int = Field(strict=True, gt=0)

    @field_validator(
        "sequence_id",
        "start_ms",
        "duration_ms",
        "size_bytes",
        mode="before",
    )
    @classmethod
    def require_integers(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("timing, sequence, and size fields must be integers")
        return value


class MockSessionRequest(ContractModel):
    """Request body for creating a mock session; forbids extra fields."""


class MockSessionResponse(ContractModel):
    """Finite run mock session response returned by POST /api/sessions/mock."""

    session_id: str = Field(min_length=1, pattern=r"\S")
    state: Literal["completed"] = "completed"
    mode: Literal["mock"] = "mock"
    events: list[EventEnvelope[Any]] = Field(default_factory=list)
