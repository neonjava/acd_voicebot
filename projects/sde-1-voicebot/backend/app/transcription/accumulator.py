"""Ordered segment accumulator for transcript events and segments."""

import math

from app.contracts.transcription import TranscriptEvent, TranscriptSegment


class SegmentAccumulator:
    """Accumulates TranscriptSegment events in deterministic order.

    - Maintains transcript order: (start_ms, sequence_id, segment_id).
    - Same segment ID replaces interim with final.
    - Tracks text revisions under the same segment ID.
    - Out-of-order arrivals are chronologically ordered.
    - Stale interim updates (lower sequence_id) are rejected.
    - Exact duplicate events are suppressed without duplicating text or revision count.
    - Final segments cannot regress to interim.
    - Rejects mixed sessions in one accumulator.
    - Error events do not become transcript segments.
    """

    def __init__(self, *, confidence_threshold: float = 0.4) -> None:
        if (
            type(confidence_threshold) not in (int, float)
            or math.isnan(confidence_threshold)
            or math.isinf(confidence_threshold)
            or not (0.0 <= confidence_threshold <= 1.0)
        ):
            raise ValueError("confidence_threshold must be a float between 0.0 and 1.0")
        self.confidence_threshold = float(confidence_threshold)
        self._session_id: str | None = None
        self._segments: dict[str, TranscriptSegment] = {}
        self._revisions: dict[str, int] = {}

    def is_low_confidence(self, segment: TranscriptSegment) -> bool:
        """Check whether a segment falls below the confidence threshold."""
        return (
            segment.confidence is not None
            and segment.confidence < self.confidence_threshold
        )

    @property
    def session_id(self) -> str | None:
        """Current session ID tracked by this accumulator."""
        return self._session_id

    def add(self, item: TranscriptEvent | TranscriptSegment) -> bool:
        """Add a transcript event or segment to the accumulator.

        Returns True if the segment was added or modified, False if ignored.
        """
        if isinstance(item, TranscriptEvent):
            # Error events do not become transcript segments
            if item.event_type == "transcript.error":
                return False
            segment = item.payload
            if not isinstance(segment, TranscriptSegment):
                raise ValueError("payload must be a TranscriptSegment")
        elif isinstance(item, TranscriptSegment):
            segment = item
        else:
            raise TypeError(
                "event must be an instance of TranscriptEvent or TranscriptSegment"
            )

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

            # 1. Final cannot regress to interim
            if existing.is_final and not segment.is_final:
                return False

            # 2. Exact duplicate check: suppress without modifying
            if (
                existing.sequence_id == segment.sequence_id
                and existing.start_ms == segment.start_ms
                and existing.end_ms == segment.end_ms
                and existing.text == segment.text
                and existing.confidence == segment.confidence
                and existing.language == segment.language
                and existing.is_final == segment.is_final
            ):
                return False

            # 3. Reject stale interim updates arriving after newer interim
            if (
                not existing.is_final
                and not segment.is_final
                and segment.sequence_id < existing.sequence_id
            ):
                return False

            # 4. Revision tracking: if text changed, increment counter
            if existing.text != segment.text:
                self._revisions[segment_id] = self._revisions.get(segment_id, 0) + 1

            self._segments[segment_id] = segment
            return True

        # New segment
        self._segments[segment_id] = segment
        self._revisions[segment_id] = 0
        return True

    def segments(self) -> list[TranscriptSegment]:
        """Return accumulated segments in (start_ms, sequence_id, segment_id) order."""
        return sorted(
            self._segments.values(),
            key=lambda s: (s.start_ms, s.sequence_id, s.segment_id),
        )

    def final_segments(
        self, *, include_low_confidence: bool = False
    ) -> list[TranscriptSegment]:
        """Return only finalized segments in chronological order.

        By default, low-confidence segments are excluded so they are never sent on
        as final text without an explicit flag.
        """
        finals = [s for s in self.segments() if s.is_final]
        if include_low_confidence:
            return finals
        return [s for s in finals if not self.is_low_confidence(s)]

    def interim_segments(self) -> list[TranscriptSegment]:
        """Return only interim segments in chronological order."""
        return [s for s in self.segments() if not s.is_final]

    def low_confidence_segments(self) -> list[TranscriptSegment]:
        """Return all segments falling below the confidence threshold."""
        return [s for s in self.segments() if self.is_low_confidence(s)]

    def revisions_count(self, segment_id: str) -> int:
        """Return the number of revisions recorded for a given segment ID."""
        return self._revisions.get(segment_id, 0)

    def text(self, *, include_low_confidence: bool = True) -> str:
        """Return the combined text of all accumulated segments in order."""
        segs = self.segments()
        if not include_low_confidence:
            segs = [s for s in segs if not self.is_low_confidence(s)]
        return " ".join(s.text for s in segs)

    def final_text(self, *, include_low_confidence: bool = False) -> str:
        """Return text of finalized segments, excluding low-confidence by default."""
        return " ".join(
            s.text
            for s in self.final_segments(include_low_confidence=include_low_confidence)
        )

    def gaps(self, min_gap_ms: int = 0) -> list[tuple[int, int]]:
        """Return chronological gaps (start_ms, end_ms) between segments."""
        if min_gap_ms < 0:
            raise ValueError("min_gap_ms must be nonnegative")

        ordered = self.segments()
        if not ordered:
            return []

        detected_gaps: list[tuple[int, int]] = []
        max_covered_end = ordered[0].end_ms

        for seg in ordered[1:]:
            if seg.start_ms > max_covered_end + min_gap_ms:
                detected_gaps.append((max_covered_end, seg.start_ms))
            max_covered_end = max(max_covered_end, seg.end_ms)

        return detected_gaps

    def clear(self) -> None:
        """Clear all stored segments and reset session ID."""
        self._session_id = None
        self._segments.clear()
        self._revisions.clear()
