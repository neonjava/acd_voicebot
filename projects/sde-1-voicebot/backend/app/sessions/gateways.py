"""Module gateways connecting Backend (W5) to Audio, STT, Reasoning, and Workflow."""

import logging
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

from app.contracts.audio import AudioChunk, SpeechEvent
from app.contracts.common import ErrorEnvelope
from app.contracts.reasoning import (
    ContextItem,
    ReasoningRequest,
    ReasoningResult,
    SourceReference,
)
from app.contracts.sessions import AudioChunkMetadata, ModuleHealthStatus
from app.contracts.transcription import TranscriptEvent, TranscriptSegment
from app.contracts.workflow import (
    ApprovalRequest,
    AuditEvent,
    WorkflowPlan,
    WorkflowProposal,
    WorkflowResult,
    WorkflowStep,
)

logger = logging.getLogger("voicebot.gateways")


class GatewayError(Exception):
    """Normalized gateway exception wrapping an ErrorEnvelope."""

    def __init__(self, envelope: ErrorEnvelope) -> None:
        super().__init__(envelope.message_safe_for_user)
        self.envelope = envelope


class AudioGateway:
    """Gateway interfacing with Audio (W1) module."""

    def health(self) -> ModuleHealthStatus:
        """Check audio subsystem health."""
        try:
            import app.audio.chunker  # noqa: F401
            import app.audio.source  # noqa: F401

            return "mock"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Audio health check failed: %s", type(exc).__name__)
            return "down"

    def produce_audio_and_speech(
        self,
        session_id: str,
        correlation_id: str,
        *,
        duration_ms: int = 1000,
        timestamp: datetime | None = None,
    ) -> tuple[list[AudioChunk], list[AudioChunkMetadata], list[SpeechEvent]]:
        """Call W1 source and chunker, producing chunks and ordered SpeechEvents."""
        ts = timestamp or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        try:
            from app.audio.chunker import chunk_pcm
            from app.audio.source import make_fake_pcm

            pcm = make_fake_pcm(duration_ms=duration_ms)
            chunks = chunk_pcm(pcm, session_id=session_id, chunk_ms=20)

            # Metadata projection for clients
            metadata = [
                AudioChunkMetadata(
                    sequence_id=0,
                    start_ms=0,
                    duration_ms=duration_ms,
                    sample_rate_hz=16000,
                    channels=1,
                    size_bytes=len(pcm),
                )
            ]

            # Ordered SpeechEvents: wake -> speech_start -> speech_end
            speech_events = [
                SpeechEvent(
                    kind="wake",
                    session_id=session_id,
                    correlation_id=correlation_id,
                    sequence_id=0,
                    at_ms=0,
                    wake_word="hey_jarvis",
                    score=0.96,
                ),
                SpeechEvent(
                    kind="speech_start",
                    session_id=session_id,
                    correlation_id=correlation_id,
                    sequence_id=1,
                    at_ms=20,
                ),
                SpeechEvent(
                    kind="speech_end",
                    session_id=session_id,
                    correlation_id=correlation_id,
                    sequence_id=2,
                    at_ms=duration_ms,
                ),
            ]

            return chunks, metadata, speech_events

        except Exception as exc:  # noqa: BLE001
            envelope = ErrorEnvelope(
                code="AUDIO_PROCESSING_FAILED",
                message_safe_for_user="Audio capture and chunking failed.",
                retryable=True,
                correlation_id=correlation_id,
                details_redacted={"error_type": type(exc).__name__},
            )
            raise GatewayError(envelope) from exc


class TranscriptionGateway:
    """Gateway interfacing with Transcription (W2) module."""

    def health(self) -> ModuleHealthStatus:
        """Check transcription subsystem health."""
        try:
            from app.transcription.mock import FakeTranscriber

            transcriber = FakeTranscriber()
            return "mock" if transcriber.health() == "ready" else "down"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Transcription health check failed: %s", type(exc).__name__)
            return "down"

    def transcribe(
        self,
        chunks: Sequence[AudioChunk],
        *,
        session_id: str,
        correlation_id: str,
        timestamp: datetime | None = None,
    ) -> list[TranscriptEvent]:
        """Call W2 transcriber and normalize output."""
        ts = timestamp or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        try:
            from app.transcription.mock import FakeTranscriber

            transcriber = FakeTranscriber()
            return transcriber.transcribe(
                chunks,
                session_id=session_id,
                correlation_id=correlation_id,
                timestamp=ts,
            )
        except Exception as exc:  # noqa: BLE001
            envelope = ErrorEnvelope(
                code="TRANSCRIPTION_FAILED",
                message_safe_for_user="Transcription failed to process audio chunks.",
                retryable=True,
                correlation_id=correlation_id,
                details_redacted={"error_type": type(exc).__name__},
            )
            raise GatewayError(envelope) from exc


class ReasoningGateway:
    """Gateway interfacing with Context and Reasoning (W3) module."""

    def health(self) -> ModuleHealthStatus:
        """Check reasoning subsystem health."""
        try:
            import app.reasoning.mock  # noqa: F401

            return "mock"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Reasoning health check failed: %s", type(exc).__name__)
            return "down"

    def reason_from_transcript(
        self,
        *,
        session_id: str,
        correlation_id: str,
        segments: Sequence[TranscriptSegment],
        question: str = "What was said?",
    ) -> ReasoningResult:
        """Convert transcript segments to context items and call reasoning."""
        try:
            from app.reasoning.mock import reason

            context_items: list[ContextItem] = []
            for seg in segments:
                try:
                    from app.reasoning.context import (
                        context_item_from_transcript,
                    )

                    item = context_item_from_transcript(seg)
                except Exception:  # noqa: BLE001
                    item = ContextItem(
                        item_id=seg.segment_id,
                        text=seg.text,
                        source=SourceReference(
                            source_id=seg.segment_id,
                            locator=seg.segment_id,
                            kind="transcript",
                        ),
                    )
                context_items.append(item)

            req = ReasoningRequest(
                request_id=f"reason-{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                question=question,
                context=context_items,
            )
            return reason(req)
        except Exception as exc:  # noqa: BLE001
            envelope = ErrorEnvelope(
                code="REASONING_FAILED",
                message_safe_for_user="Reasoning failed to process context.",
                retryable=False,
                correlation_id=correlation_id,
                details_redacted={"error_type": type(exc).__name__},
            )
            raise GatewayError(envelope) from exc


class WorkflowGateway:
    """Gateway interfacing with Workflow and Agent (W4) module."""

    def health(self) -> ModuleHealthStatus:
        """Check workflow subsystem health."""
        try:
            import app.agent.executor  # noqa: F401

            return "mock"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Workflow health check failed: %s", type(exc).__name__)
            return "down"

    def build_proposal_and_plan(
        self,
        *,
        session_id: str,
        correlation_id: str,
        text_to_echo: str,
        source_ids: list[str] | None = None,
    ) -> tuple[WorkflowProposal, WorkflowPlan, ApprovalRequest]:
        """Construct a proposal, plan, and initial approval request."""
        try:
            plan_id = f"plan-{uuid.uuid4().hex[:8]}"
            step_id = f"step-{uuid.uuid4().hex[:6]}"
            approval_id = f"appr-{uuid.uuid4().hex[:8]}"

            step = WorkflowStep(
                step_id=step_id,
                tool_name="echo_text",
                arguments={"text": text_to_echo},
                requires_approval=True,
            )

            srcs = source_ids or [f"src-{uuid.uuid4().hex[:6]}"]
            proposal = WorkflowProposal(
                proposal_id=f"prop-{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                correlation_id=correlation_id,
                summary=f"Echo reasoning response: {text_to_echo[:60]}",
                steps=[step],
                source_ids=srcs,
            )

            plan = WorkflowPlan(
                plan_id=plan_id,
                session_id=session_id,
                steps=[step],
            )

            approval = ApprovalRequest(
                approval_id=approval_id,
                plan_id=plan_id,
                step_id=step_id,
                session_id=session_id,
                status="pending",
            )

            return proposal, plan, approval
        except Exception as exc:  # noqa: BLE001
            envelope = ErrorEnvelope(
                code="WORKFLOW_PLANNING_FAILED",
                message_safe_for_user="Failed to construct workflow plan.",
                retryable=False,
                correlation_id=correlation_id,
                details_redacted={"error_type": type(exc).__name__},
            )
            raise GatewayError(envelope) from exc

    def execute_plan(
        self,
        plan: WorkflowPlan,
        approvals: Sequence[ApprovalRequest],
        *,
        correlation_id: str,
    ) -> tuple[WorkflowResult, list[AuditEvent]]:
        """Execute workflow plan using W4 executor and generate AuditEvents."""
        try:
            from app.agent.executor import execute

            result = execute(plan, approvals=approvals)

            audit_events: list[AuditEvent] = []
            seq = 0
            for appr in approvals:
                if appr.status == "approved":
                    audit_events.append(
                        AuditEvent(
                            sequence=seq,
                            kind="approval_granted",
                            plan_id=plan.plan_id,
                            session_id=plan.session_id,
                            step_id=appr.step_id,
                            approval_id=appr.approval_id,
                        )
                    )
                    seq += 1
                elif appr.status == "rejected":
                    audit_events.append(
                        AuditEvent(
                            sequence=seq,
                            kind="approval_rejected",
                            plan_id=plan.plan_id,
                            session_id=plan.session_id,
                            step_id=appr.step_id,
                            approval_id=appr.approval_id,
                        )
                    )
                    seq += 1

            if result.state.value == "succeeded":
                for step in plan.steps:
                    audit_events.append(
                        AuditEvent(
                            sequence=seq,
                            kind="step_succeeded",
                            plan_id=plan.plan_id,
                            session_id=plan.session_id,
                            step_id=step.step_id,
                        )
                    )
                    seq += 1
            elif result.state.value == "cancelled":
                audit_events.append(
                    AuditEvent(
                        sequence=seq,
                        kind="workflow_cancelled",
                        plan_id=plan.plan_id,
                        session_id=plan.session_id,
                    )
                )

            return result, audit_events

        except Exception as exc:  # noqa: BLE001
            envelope = ErrorEnvelope(
                code="WORKFLOW_EXECUTION_FAILED",
                message_safe_for_user="Workflow execution failed.",
                retryable=False,
                correlation_id=correlation_id,
                details_redacted={"error_type": type(exc).__name__},
            )
            raise GatewayError(envelope) from exc


# Shared gateway singleton instances
audio_gateway = AudioGateway()
transcription_gateway = TranscriptionGateway()
reasoning_gateway = ReasoningGateway()
workflow_gateway = WorkflowGateway()
