"""Synthetic screen context and the W2 transcript handoff."""

from datetime import datetime, timezone

from app.contracts.reasoning import ContextItem, ScreenContext, SourceReference
from app.contracts.transcription import TranscriptSegment


def make_synthetic_screen_context() -> ScreenContext:
    """Return fixed demo data without reading the screen or asking permission."""
    return ScreenContext(
        frame_id="frame-demo-0",
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        items=[
            ContextItem(
                item_id="screen-status",
                text="Mock dashboard status: ready.",
                source=SourceReference(
                    source_id="screen-status",
                    kind="synthetic_screen",
                    locator="demo-dashboard",
                ),
            )
        ],
    )


def context_item_from_transcript(segment: TranscriptSegment) -> ContextItem:
    """Map one final W2 segment to the exact agreed source-linked shape."""
    if not isinstance(segment, TranscriptSegment):
        raise TypeError("segment must be a TranscriptSegment")
    if not segment.is_final:
        raise ValueError("only final transcript segments can become context")
    return ContextItem(
        item_id=segment.segment_id,
        text=segment.text,
        source=SourceReference(
            source_id=segment.segment_id,
            kind="transcript",
            locator=segment.segment_id,
        ),
    )
