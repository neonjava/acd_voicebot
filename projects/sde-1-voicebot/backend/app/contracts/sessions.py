"""Session contracts and wire projections owned by W5 (Backend)."""

from datetime import datetime
from typing import Any, Literal, Self, Union

from pydantic import Field, field_validator, model_validator

from app.contracts.common import ContractModel, EventEnvelope, SessionState
from app.contracts.transcription import TranscriptEvent


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


class AudioChunkEvent(EventEnvelope[AudioChunkMetadata]):
    """Typed event envelope for wire audio chunk metadata."""

    producer: Literal["audio"] = "audio"
    event_type: Literal["audio.chunk"] = "audio.chunk"


SessionEvent = Union[AudioChunkEvent, TranscriptEvent]


class MockSessionRequest(ContractModel):
    """Request body for creating a mock session; forbids extra fields."""


class MockSessionResponse(ContractModel):
    """Finite run mock session response returned by POST /api/sessions/mock."""

    session_id: str = Field(min_length=1, pattern=r"\S")
    state: Literal["completed"] = "completed"
    mode: Literal["mock"] = "mock"
    events: list[SessionEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_events(self) -> Self:
        """Enforce event ordering, session scoping, and consistent correlation ID."""
        seen_transcript = False
        expected_corr_id = self.events[0].correlation_id if self.events else None

        for evt in self.events:
            if evt.session_id != self.session_id:
                raise ValueError(
                    f"Event session_id '{evt.session_id}' does not match "
                    f"response session_id '{self.session_id}'"
                )

            if evt.correlation_id != expected_corr_id:
                raise ValueError(
                    f"Inconsistent correlation_id across events: expected "
                    f"'{expected_corr_id}', got '{evt.correlation_id}'"
                )

            if evt.event_type.startswith("transcript."):
                seen_transcript = True
            elif evt.event_type == "audio.chunk" and seen_transcript:
                raise ValueError("audio.chunk events must precede transcript events")

        return self


# --- Week 2 Full Lifecycle Models ---


class SessionCreateRequest(ContractModel):
    """Request payload for creating a new voicebot session."""

    session_id: str | None = Field(default=None, min_length=1, pattern=r"\S")
    mode: Literal["mock"] = "mock"
    initial_state: Literal["created", "active"] = "created"


class SessionActionRequest(ContractModel):
    """Generic payload for lifecycle action commands (pause/resume/stop)."""

    reason: str | None = Field(default=None, max_length=256)


class SessionStateResponse(ContractModel):
    """Normalized wire representation of a session's current lifecycle state."""

    session_id: str = Field(min_length=1, pattern=r"\S")
    state: SessionState
    mode: Literal["mock"] = "mock"
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None


class SessionEventStreamResponse(ContractModel):
    """Batch of ordered session events returned by replay / polling."""

    session_id: str = Field(min_length=1, pattern=r"\S")
    events: list[SessionEvent] = Field(default_factory=list)
    from_sequence: int = Field(ge=0, default=0)
    total_events: int = Field(ge=0, default=0)
    has_more: bool = False


class IdempotencyRecord(ContractModel):
    """Cached response for an idempotent operation."""

    idempotency_key: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    status_code: int = Field(ge=200, le=599)
    response_body: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
