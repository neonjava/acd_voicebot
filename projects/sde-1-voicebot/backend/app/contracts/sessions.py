"""Session contracts and wire projections owned by W5 (Backend)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self, Union

from pydantic import Field, field_validator, model_validator

from app.contracts.audio import CaptureStatus, SpeechEvent
from app.contracts.browser import BrowserAction
from app.contracts.common import ContractModel, EventEnvelope, SessionState
from app.contracts.transcription import TranscriptEvent
from app.contracts.workflow import (
    ApprovalRequest,
    AuditEvent,
    WorkflowProposal,
    WorkflowResult,
)


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


class SpeechStreamEvent(EventEnvelope[SpeechEvent]):
    """Session stream envelope for speech events (wake, speech_start, speech_end)."""

    producer: Literal["audio"] = "audio"
    event_type: Literal["audio.speech"] = "audio.speech"


class WorkflowAuditEvent(EventEnvelope[AuditEvent]):
    """Session stream envelope for workflow audit events."""

    producer: Literal["workflow"] = "workflow"
    event_type: Literal["workflow.audit"] = "workflow.audit"


# (Forward-declared SessionEvent defined after Week 4 models)


class MockSessionRequest(ContractModel):
    """Request body for creating a mock session; forbids extra fields."""


class MockSessionResponse(ContractModel):
    """Finite run mock session response returned by POST /api/sessions/mock."""

    session_id: str = Field(min_length=1, pattern=r"\S")
    state: Literal["active", "completed"] = "active"
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


# --- Week 3 Approvals & Health Contracts ---


class ApprovalDecisionRequest(ContractModel):
    """Payload for deciding a pending approval request."""

    decision: Literal["approve", "reject"]


ModuleHealthStatus = Literal["ok", "degraded", "down", "mock"]
OverallHealthStatus = Literal["ok", "degraded", "down"]


class HealthResponse(ContractModel):
    """Aggregated health status covering all module gateways."""

    status: OverallHealthStatus
    mode: Literal["mock"] = "mock"
    modules: dict[str, ModuleHealthStatus]


# --- Week 4: conversational turns (W5 implements, W6 consumes) ---


class TurnRequest(ContractModel):
    """One thing the user said or typed to the assistant."""

    text: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    active_app: str | None = Field(default=None, max_length=200)
    active_window_title: str | None = Field(default=None, max_length=500)


TurnKind = Literal["answer", "clarify", "proposal", "error"]


class TurnResponse(ContractModel):
    """The assistant's reply to one turn.

    - ``answer``: ``answer`` is set, citing ``source_ids`` (empty means the
      evidence was insufficient and the answer says so).
    - ``clarify``: ``clarify`` holds one short question.
    - ``proposal``: ``proposal`` is set. ``approvals`` lists the pending
      approvals it needs; ``workflow`` is set when only safe steps ran directly.
    - ``error``: ``error_code`` holds a safe error code.
    ``spoken_text`` is the short text the assistant speaks (TTS), if any.
    """

    session_id: str = Field(min_length=1, pattern=r"\S")
    turn_id: str = Field(min_length=1, pattern=r"\S")
    kind: TurnKind
    answer: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    clarify: str | None = Field(default=None, max_length=300)
    proposal: WorkflowProposal | None = None
    approvals: list[ApprovalRequest] = Field(default_factory=list)
    workflow: WorkflowResult | None = None
    error_code: str | None = None
    spoken_text: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def fields_match_kind(self) -> Self:
        required = {
            "answer": self.answer,
            "clarify": self.clarify,
            "proposal": self.proposal,
            "error": self.error_code,
        }
        if required[self.kind] is None:
            raise ValueError(f"a {self.kind} turn needs its {self.kind} field")
        if self.kind != "proposal" and (self.approvals or self.workflow):
            raise ValueError("approvals and workflow belong to proposal turns")
        if any(
            sid != self.session_id for sid in [a.session_id for a in self.approvals]
        ):
            raise ValueError("approvals must belong to this session")
        return self


# --- Week 4 Stream Events & Union ---


class CaptureListenRequest(ContractModel):
    """Payload for starting or stopping microphone capture."""

    action: Literal["start", "stop"]


class AudioCaptureEvent(EventEnvelope[CaptureStatus]):
    """Session stream envelope for audio capture status changes."""

    producer: Literal["audio"] = "audio"
    event_type: Literal["audio.capture"] = "audio.capture"


class AssistantTurnEvent(EventEnvelope[TurnResponse]):
    """Session stream envelope for assistant conversational turn responses."""

    producer: Literal["assistant"] = "assistant"
    event_type: Literal["assistant.turn"] = "assistant.turn"


class BrowserActionPayload(ContractModel):
    """Payload for browser action events without sensitive snapshot text."""

    action: BrowserAction
    ok: bool
    error_code: str | None = None


class BrowserActionEvent(EventEnvelope[BrowserActionPayload]):
    """Session stream envelope for browser actions executed via the extension bridge."""

    producer: Literal["browser"] = "browser"
    event_type: Literal["browser.action"] = "browser.action"


SessionEvent = Union[
    AudioChunkEvent,
    TranscriptEvent,
    SpeechStreamEvent,
    WorkflowAuditEvent,
    AudioCaptureEvent,
    AssistantTurnEvent,
    BrowserActionEvent,
]

MockSessionResponse.model_rebuild()
SessionEventStreamResponse.model_rebuild()
