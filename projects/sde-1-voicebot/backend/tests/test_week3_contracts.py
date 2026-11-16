"""Validation tests for the shared Week 3 contracts (SpeechEvent, WorkflowProposal)."""

import pytest
from pydantic import ValidationError

from app.contracts.audio import SpeechEvent
from app.contracts.workflow import WorkflowProposal, WorkflowStep

IDS = {"session_id": "session-demo", "correlation_id": "correlation-demo"}


def test_wake_event_requires_word_and_score():
    event = SpeechEvent(
        kind="wake", sequence_id=0, at_ms=120, wake_word="hey_jarvis", score=0.91, **IDS
    )
    assert event.wake_word == "hey_jarvis"
    with pytest.raises(ValidationError, match="wake events need"):
        SpeechEvent(kind="wake", sequence_id=0, at_ms=0, **IDS)


@pytest.mark.parametrize("kind", ["speech_start", "speech_end"])
def test_speech_events_reject_wake_fields(kind):
    SpeechEvent(kind=kind, sequence_id=1, at_ms=500, **IDS)
    with pytest.raises(ValidationError, match="only allowed on wake"):
        SpeechEvent(kind=kind, sequence_id=1, at_ms=500, score=0.5, **IDS)


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "noise"},
        {"sequence_id": -1},
        {"at_ms": -5},
        {"sequence_id": "1"},
        {"session_id": " "},
        {"correlation_id": ""},
        {"pcm": b"\x00\x00"},
    ],
)
def test_speech_event_rejects_invalid_fields(changes):
    data = {"kind": "speech_start", "sequence_id": 0, "at_ms": 0, **IDS, **changes}
    with pytest.raises(ValidationError):
        SpeechEvent(**data)


def _step(step_id: str, *depends_on: str) -> WorkflowStep:
    return WorkflowStep(
        step_id=step_id,
        tool_name="open_url",
        arguments={"url": "https://www.youtube.com"},
        depends_on=list(depends_on),
    )


def test_workflow_proposal_accepts_ordered_steps():
    proposal = WorkflowProposal(
        proposal_id="proposal-1",
        summary="Open YouTube and play the third video",
        steps=[_step("open"), _step("play", "open")],
        source_ids=["transcript-segment-0"],
        **IDS,
    )
    assert [step.step_id for step in proposal.steps] == ["open", "play"]
    assert proposal.steps[0].requires_approval is True


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"steps": [_step("a"), _step("a")]}, "step IDs must be unique"),
        ({"steps": [_step("a", "missing")]}, "depends_on must reference"),
        ({"source_ids": ["s1", "s1"]}, "source_ids must be unique"),
        ({"source_ids": [" "]}, "source_ids must be nonblank"),
        ({"steps": []}, "at least 1"),
        ({"summary": "x" * 501}, "at most 500"),
    ],
)
def test_workflow_proposal_rejects_invalid_shapes(changes, message):
    data = {
        "proposal_id": "p",
        "summary": "Do it",
        "steps": [_step("a")],
        **IDS,
        **changes,
    }
    with pytest.raises(ValidationError, match=message):
        WorkflowProposal(**data)
