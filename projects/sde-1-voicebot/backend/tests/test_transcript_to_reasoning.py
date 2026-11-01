"""Use W2's real transcript contract as W3 context input."""

from app.contracts.reasoning import ReasoningRequest
from app.contracts.transcription import TranscriptSegment
from app.reasoning.context import context_item_from_transcript
from app.reasoning.mock import reason


def test_final_transcript_segment_maps_to_source_linked_context():
    segment = TranscriptSegment(
        segment_id="session-demo-segment-0",
        session_id="session-demo",
        sequence_id=0,
        start_ms=0,
        end_ms=1000,
        text="Hello from the mock voicebot.",
        confidence=1.0,
        language="en",
        is_final=True,
    )
    item = context_item_from_transcript(segment)
    assert item.item_id == segment.segment_id
    assert item.text == segment.text
    assert item.source.source_id == segment.segment_id
    assert item.source.kind == "transcript"
    assert item.source.locator == segment.segment_id

    result = reason(
        ReasoningRequest(
            request_id="reasoning-transcript-0",
            session_id=segment.session_id,
            question="What was said?",
            context=[item],
        )
    )
    assert result.source_ids == [segment.segment_id]
    assert result.insufficient_evidence is False


def test_interim_segment_cannot_be_used_as_final_context():
    segment = TranscriptSegment(
        segment_id="segment-interim",
        session_id="session-demo",
        sequence_id=0,
        start_ms=0,
        end_ms=1000,
        text="Partial transcript",
        is_final=False,
    )
    try:
        context_item_from_transcript(segment)
    except ValueError as exc:
        assert "final transcript" in str(exc)
    else:
        raise AssertionError("interim transcript was incorrectly accepted")
