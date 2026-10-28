"""Ordered segment accumulator for transcript events and segments."""

from app.contracts.transcription import TranscriptEvent, TranscriptSegment


class SegmentAccumulator:
    """Accumulates TranscriptSegment events in deterministic order.

    - Maintains transcript order: (start_ms, sequence_id, segment_id).
    - Same segment ID replaces interim with final.
    - Repeats do not duplicate.
    - Final segments cannot regress to interim.
    - Rejects mixed sessions in one accumulator.
    - Error events do not become transcript segments.
    """

    def __init__(self) -> None:
        self._session_id: str | None = None
        self._segments: dict[str, TranscriptSegment] = {}

    @property
    def session_id(self) -> str | None:
        """Current session ID tracked by this accumulator."""
        return self._session_id

    def add(self, event: TranscriptEvent) -> None:
        """Add a transcript event to the accumulator."""
        if not isinstance(event, TranscriptEvent):
            raise TypeError("event must be an instance of TranscriptEvent")

        # Error events do not become transcript segments
        if event.event_type == "transcript.error":
            return

        segment = event.payload
        if not isinstance(segment, TranscriptSegment):
            raise ValueError("payload must be a TranscriptSegment")

        # Reject mixed sessions in one accumulator
        if self._session_id is None:
            self._session_id = segment.session_id
        elif self._session_id != segment.session_id:
            raise ValueError(
                f"Cannot add event with session_id '{segment.session_id}' to "
                f"accumulator initialized with session_id '{self._session_id}'"
            )

        segment_id = segment.segment_id
        if segment_id in self._segments:
            existing = self._segments[segment_id]
            # Final cannot regress to interim
            if existing.is_final and not segment.is_final:
                return

            # Same segment ID replaces interim with final, or updates interim
            # Repeats of final do not duplicate
            self._segments[segment_id] = segment
        else:
            self._segments[segment_id] = segment

    def segments(self) -> list[TranscriptSegment]:
        """Return accumulated segments in (start_ms, sequence_id, segment_id) order."""
        return sorted(
            self._segments.values(),
            key=lambda s: (s.start_ms, s.sequence_id, s.segment_id),
        )

    def text(self) -> str:
        """Return the combined text of all accumulated segments in order."""
        return " ".join(s.text for s in self.segments())

    def clear(self) -> None:
        """Clear all stored segments and reset session ID."""
        self._session_id = None
        self._segments.clear()
