"""Validation tests for the shared Week 4 contracts (CaptureStatus, turns)."""

import pytest
from pydantic import ValidationError

from app.contracts.audio import CaptureStatus
from app.contracts.sessions import TurnRequest, TurnResponse
from app.contracts.workflow import ApprovalRequest, WorkflowProposal, WorkflowStep

SID = "session-demo"


def test_capture_status_states_and_rejections() -> None:
    status = CaptureStatus(
        session_id=SID,
        state="listening",
        source="mic",
        wake_required=True,
        wake_word="hey_jarvis",
    )
    assert status.state == "listening"
    for bad in (
        {"state": "recording_to_disk"},
        {"source": "cloud"},
        {"session_id": " "},
    ):
        with pytest.raises(ValidationError):
            CaptureStatus(
                **{
                    "session_id": SID,
                    "state": "idle",
                    "source": "mock",
                    "wake_required": False,
                    **bad,
                }
            )


@pytest.mark.parametrize("text", ["", "   ", "x" * 2001])
def test_turn_request_rejects_blank_or_huge_text(text: str) -> None:
    with pytest.raises(ValidationError):
        TurnRequest(text=text)


def proposal() -> WorkflowProposal:
    return WorkflowProposal(
        proposal_id="p1",
        session_id=SID,
        correlation_id="c",
        summary="Close chrome",
        steps=[
            WorkflowStep(
                step_id="close", tool_name="close_app", arguments={"app": "chrome"}
            )
        ],
        source_ids=["t1"],
    )


def test_turn_response_kinds_need_their_field() -> None:
    TurnResponse(
        session_id=SID, turn_id="t1", kind="answer", answer="Hi", source_ids=["s"]
    )
    TurnResponse(session_id=SID, turn_id="t1", kind="clarify", clarify="Which app?")
    TurnResponse(
        session_id=SID, turn_id="t1", kind="error", error_code="REASONING_TIMEOUT"
    )
    approval = ApprovalRequest(
        approval_id="a1", plan_id="p1", step_id="close", session_id=SID
    )
    TurnResponse(
        session_id=SID,
        turn_id="t1",
        kind="proposal",
        proposal=proposal(),
        approvals=[approval],
    )
    for kind in ("answer", "clarify", "proposal", "error"):
        with pytest.raises(ValidationError, match="needs its"):
            TurnResponse(session_id=SID, turn_id="t1", kind=kind)


def test_turn_response_rejects_approvals_outside_proposals_or_session() -> None:
    other = ApprovalRequest(
        approval_id="a1", plan_id="p1", step_id="close", session_id="x"
    )
    with pytest.raises(ValidationError, match="belong to proposal"):
        TurnResponse(
            session_id=SID,
            turn_id="t1",
            kind="answer",
            answer="Hi",
            approvals=[other.model_copy(update={"session_id": SID})],
        )
    with pytest.raises(ValidationError, match="this session"):
        TurnResponse(
            session_id=SID,
            turn_id="t1",
            kind="proposal",
            proposal=proposal(),
            approvals=[other],
        )


def test_source_reference_accepts_note_kind_for_rag() -> None:
    from app.contracts.reasoning import SourceReference

    ref = SourceReference(
        source_id="notes/todo.md#2", locator="notes/todo.md#2", kind="note"
    )
    assert ref.kind == "note"
    with pytest.raises(ValidationError):
        SourceReference(source_id="x", locator="x", kind="web")
