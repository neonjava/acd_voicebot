"""Tests for module gateways connecting Audio, STT, Reasoning, and Workflow."""

from unittest.mock import patch

import pytest

from app.contracts.common import SessionState, WorkflowState
from app.sessions.gateways import (
    AudioGateway,
    GatewayError,
    ReasoningGateway,
    TranscriptionGateway,
    WorkflowGateway,
)
from app.sessions.service import session_service


@pytest.fixture(autouse=True)
def clean_service():
    session_service.clear()
    yield
    session_service.clear()


def test_audio_gateway_produces_chunks_and_speech_events():
    """AudioGateway produces audio chunks, metadata, and ordered SpeechEvents."""
    gw = AudioGateway()
    chunks, metadata, speech_events = gw.produce_audio_and_speech(
        session_id="session-audio-gw",
        correlation_id="corr-audio-gw",
        duration_ms=1000,
    )
    assert len(chunks) == 50  # 1000ms at 20ms chunks
    assert len(metadata) == 1
    assert metadata[0].duration_ms == 1000
    assert metadata[0].size_bytes == 32000

    assert len(speech_events) == 3
    assert [e.kind for e in speech_events] == ["wake", "speech_start", "speech_end"]
    assert speech_events[0].wake_word == "hey_jarvis"
    assert speech_events[0].score is not None
    assert speech_events[0].session_id == "session-audio-gw"
    assert speech_events[0].correlation_id == "corr-audio-gw"
    assert gw.health() in ("ok", "mock")


def test_audio_gateway_error_normalization():
    """Exceptions in audio processing are converted to typed ErrorEnvelope."""
    gw = AudioGateway()
    with patch(
        "app.audio.source.make_fake_pcm", side_effect=RuntimeError("Mic disconnected")
    ):
        with pytest.raises(GatewayError) as exc_info:
            gw.produce_audio_and_speech(
                session_id="session-err",
                correlation_id="corr-err",
            )
        err = exc_info.value.envelope
        assert err.code == "AUDIO_PROCESSING_FAILED"
        assert err.retryable is True
        assert err.correlation_id == "corr-err"


def test_transcription_gateway_transcribes_and_handles_health():
    """TranscriptionGateway calls transcriber and reports mock health."""
    audio_gw = AudioGateway()
    chunks, _, _ = audio_gw.produce_audio_and_speech(
        session_id="session-stt-gw",
        correlation_id="corr-stt-gw",
    )

    gw = TranscriptionGateway()
    assert gw.health() == "mock"
    events = gw.transcribe(
        chunks,
        session_id="session-stt-gw",
        correlation_id="corr-stt-gw",
    )
    assert len(events) >= 1
    assert events[0].event_type == "transcript.segment"
    assert events[0].session_id == "session-stt-gw"
    assert events[0].correlation_id == "corr-stt-gw"


def test_transcription_gateway_error_normalization():
    """Exceptions in transcription are normalized into ErrorEnvelope."""
    gw = TranscriptionGateway()
    with patch(
        "app.transcription.mock.FakeTranscriber.transcribe",
        side_effect=ValueError("Model crashed"),
    ):
        with pytest.raises(GatewayError) as exc_info:
            gw.transcribe(
                [], session_id="session-stt-err", correlation_id="corr-stt-err"
            )
        err = exc_info.value.envelope
        assert err.code == "TRANSCRIPTION_FAILED"
        assert err.retryable is True
        assert err.correlation_id == "corr-stt-err"


def test_reasoning_gateway_reasons_over_transcript_segments():
    """ReasoningGateway converts segments into context and queries mock reasoning."""
    audio_gw = AudioGateway()
    chunks, _, _ = audio_gw.produce_audio_and_speech(
        session_id="session-reas-gw",
        correlation_id="corr-reas-gw",
    )
    trans_gw = TranscriptionGateway()
    trans_events = trans_gw.transcribe(
        chunks,
        session_id="session-reas-gw",
        correlation_id="corr-reas-gw",
    )
    segments = [e.payload for e in trans_events if e.event_type == "transcript.segment"]

    gw = ReasoningGateway()
    assert gw.health() == "mock"
    result = gw.reason_from_transcript(
        session_id="session-reas-gw",
        correlation_id="corr-reas-gw",
        segments=segments,
        question="What was said?",
    )
    assert result.session_id == "session-reas-gw"
    assert len(result.answer) > 0
    assert result.insufficient_evidence is False


def test_workflow_gateway_creates_plan_and_executes_with_audit():
    """WorkflowGateway builds plan and produces AuditEvents on execution."""
    gw = WorkflowGateway()
    assert gw.health() == "mock"
    proposal, plan, approval = gw.build_proposal_and_plan(
        session_id="session-wf-gw",
        correlation_id="corr-wf-gw",
        text_to_echo="Test echo action",
    )
    assert proposal.session_id == "session-wf-gw"
    assert plan.session_id == "session-wf-gw"
    assert approval.status == "pending"

    # Execute with approved request
    approved = approval.model_copy(update={"status": "approved"})
    result, audits = gw.execute_plan(plan, [approved], correlation_id="corr-wf-gw")
    assert result.state == WorkflowState.succeeded
    assert result.outputs[plan.steps[0].step_id] == "Test echo action"
    assert len(audits) >= 2
    assert audits[0].kind == "approval_granted"
    assert audits[1].kind == "step_succeeded"


def test_workflow_gateway_rejected_approval_cancels_without_execution():
    """Rejecting approval cancels workflow and produces approval_rejected audit."""
    gw = WorkflowGateway()
    _, plan, approval = gw.build_proposal_and_plan(
        session_id="session-wf-rej",
        correlation_id="corr-wf-rej",
        text_to_echo="Secret command",
    )
    rejected = approval.model_copy(update={"status": "rejected"})
    result, audits = gw.execute_plan(plan, [rejected], correlation_id="corr-wf-rej")
    assert result.state == WorkflowState.cancelled
    assert plan.steps[0].step_id not in result.outputs
    assert any(a.kind == "approval_rejected" for a in audits)
    assert any(a.kind == "workflow_cancelled" for a in audits)


def test_end_to_end_pipeline_routes_through_all_gateways():
    """SessionService routes session through all 4 gateways end to end in mock mode."""
    record, events = session_service.run_pipeline_session(
        session_id="session-e2e-pipeline",
        correlation_id="corr-e2e-pipeline",
        question="What was said?",
        auto_approve=True,
    )
    assert record.session_id == "session-e2e-pipeline"
    assert record.state == SessionState.completed

    event_types = [e.event_type for e in events]
    # Verified: AudioChunkEvent, SpeechStreamEvent, TranscriptEvent, WorkflowAuditEvent
    assert "audio.chunk" in event_types
    assert "audio.speech" in event_types
    assert "transcript.segment" in event_types
    assert "workflow.audit" in event_types

    # Ensure consistent correlation ID propagation
    for evt in events:
        assert evt.correlation_id == "corr-e2e-pipeline"
        assert evt.session_id == "session-e2e-pipeline"


def test_workflow_gateway_failure_retains_audit_events():
    """When workflow execution fails, audit events (step_failed) are preserved."""
    gw = WorkflowGateway()
    _, plan, approval = gw.build_proposal_and_plan(
        session_id="session-wf-fail",
        correlation_id="corr-wf-fail",
        text_to_echo="Failing command",
    )
    approved = approval.model_copy(update={"status": "approved"})

    with patch("app.agent.tools.invoke_tool", side_effect=RuntimeError("Tool crashed")):
        result, audits = gw.execute_plan(
            plan, [approved], correlation_id="corr-wf-fail"
        )
        assert result.state == WorkflowState.failed
        assert len(audits) >= 2
        assert any(a.kind == "approval_granted" for a in audits)
        assert any(a.kind == "step_failed" for a in audits)


def test_reasoning_gateway_skips_interim_transcripts():
    """Reasoning gateway converts only final transcripts, skipping interim."""
    from app.contracts.transcription import TranscriptSegment

    interim = TranscriptSegment(
        segment_id="seg-interim",
        session_id="session-interim",
        sequence_id=0,
        start_ms=0,
        end_ms=500,
        text="this is interim text",
        confidence=0.5,
        language="en",
        is_final=False,
    )
    final = TranscriptSegment(
        segment_id="seg-final",
        session_id="session-interim",
        sequence_id=1,
        start_ms=0,
        end_ms=1000,
        text="this is final text",
        confidence=0.99,
        language="en",
        is_final=True,
    )

    gw = ReasoningGateway()
    with patch("app.reasoning.mock.reason") as mock_reason:
        from app.contracts.reasoning import ReasoningResult

        mock_reason.return_value = ReasoningResult(
            request_id="req-1",
            session_id="session-interim",
            answer="final answer",
            source_ids=["seg-final"],
            insufficient_evidence=False,
            prompt_version="v1",
        )
        gw.reason_from_transcript(
            session_id="session-interim",
            correlation_id="corr-interim",
            segments=[interim, final],
        )

        # Verify reason was called with only the final segment
        assert mock_reason.call_count == 1
        req = mock_reason.call_args[0][0]
        assert len(req.context) == 1
        assert req.context[0].item_id == "seg-final"
        assert req.context[0].text == "this is final text"


def test_reasoning_gateway_does_not_swallow_validation_errors():
    """Validation errors on invalid segments raise GatewayError, not swallowed."""
    gw = ReasoningGateway()
    with pytest.raises(GatewayError) as exc_info:
        gw.reason_from_transcript(
            session_id="session-bad-seg",
            correlation_id="corr-bad-seg",
            segments=["not-a-segment"],  # Invalid segment type
        )
    assert exc_info.value.envelope.code == "REASONING_FAILED"
