"""Validation of W3 context and reasoning contracts."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.contracts.reasoning import (
    ContextItem,
    ReasoningRequest,
    ReasoningResult,
    ScreenContext,
    SourceReference,
)


def item() -> ContextItem:
    return ContextItem(
        item_id="item-1",
        text="Synthetic status is ready.",
        source=SourceReference(
            source_id="source-1", kind="synthetic_screen", locator="demo-screen"
        ),
    )


def test_valid_contracts_and_defaults():
    frame = ScreenContext(
        frame_id="frame-1",
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        items=[item()],
    )
    request = ReasoningRequest(
        request_id="request-1", session_id="session-1", question="Status?"
    )
    assert frame.capture_enabled is False
    assert frame.items[0].source.source_id == "source-1"
    assert request.context == []
    assert request.prompt_version == "v1"


@pytest.mark.parametrize(
    "fields",
    [
        {"source_id": " "},
        {"locator": ""},
        {"kind": "real_screen"},
        {"unexpected": "ignored"},
    ],
)
def test_invalid_source_reference_is_rejected(fields):
    data = {"source_id": "source-1", "locator": "demo", "kind": "transcript"}
    data.update(fields)
    with pytest.raises(ValidationError):
        SourceReference.model_validate(data)


@pytest.mark.parametrize("fields", [{"item_id": ""}, {"text": "  "}])
def test_blank_context_item_is_rejected(fields):
    data = item().model_dump()
    data.update(fields)
    with pytest.raises(ValidationError):
        ContextItem.model_validate(data)


@pytest.mark.parametrize(
    "captured_at",
    [datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=5)))],
)
def test_frame_requires_utc(captured_at):
    with pytest.raises(ValidationError):
        ScreenContext(frame_id="frame-1", captured_at=captured_at)


@pytest.mark.parametrize("capture_enabled", [1, "false", None])
def test_capture_permission_requires_boolean(capture_enabled):
    with pytest.raises(ValidationError):
        ScreenContext(
            frame_id="frame-1",
            captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            capture_enabled=capture_enabled,
        )


@pytest.mark.parametrize(
    "fields",
    [
        {"request_id": ""},
        {"session_id": " "},
        {"question": "  "},
        {"prompt_version": "v2"},
        {"context": [{"item_id": "missing-source", "text": "hello"}]},
        {"unknown": True},
    ],
)
def test_invalid_reasoning_request_is_rejected(fields):
    data = {
        "request_id": "request-1",
        "session_id": "session-1",
        "question": "What is the status?",
    }
    data.update(fields)
    with pytest.raises(ValidationError):
        ReasoningRequest.model_validate(data)


@pytest.mark.parametrize(
    "fields",
    [
        {"answer": ""},
        {"source_ids": [""]},
        {"source_ids": ["source-1", "source-1"]},
        {"source_ids": []},
        {"insufficient_evidence": "false"},
        {"prompt_version": "v2"},
        {"unexpected": "ignored"},
    ],
)
def test_invalid_grounded_result_is_rejected(fields):
    data = {
        "request_id": "request-1",
        "session_id": "session-1",
        "answer": "Mock answer.",
        "source_ids": ["source-1"],
        "insufficient_evidence": False,
    }
    data.update(fields)
    with pytest.raises(ValidationError):
        ReasoningResult.model_validate(data)


def test_no_evidence_result_cannot_cite_sources():
    with pytest.raises(ValidationError):
        ReasoningResult(
            request_id="request-1",
            session_id="session-1",
            answer="No evidence.",
            source_ids=["source-1"],
            insufficient_evidence=True,
        )
