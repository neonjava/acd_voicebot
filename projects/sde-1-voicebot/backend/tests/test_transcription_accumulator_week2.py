"""Tests for Week 2 SegmentAccumulator: ordering, revisions, deduplication, and gaps."""

from datetime import datetime, timezone

import pytest

from app.contracts.common import ErrorEnvelope
from app.contracts.transcription import TranscriptEvent, TranscriptSegment
from app.transcription.accumulator import SegmentAccumulator


def _make_segment(
    segment_id: str,
    *,
    session_id: str = "sess-acc2",
    sequence_id: int = 0,
    start_ms: int = 0,
    end_ms: int = 1000,
    text: str = "Hello",
    confidence: float = 0.95,
    is_final: bool = True,
) -> TranscriptSegment:
    return TranscriptSegment(
        segment_id=segment_id,
        session_id=session_id,
        sequence_id=sequence_id,
        start_ms=start_ms,
        end_ms=end_ms,
        text=text,
        confidence=confidence,
        language="en",
        is_final=is_final,
    )


def _make_event(segment: TranscriptSegment) -> TranscriptEvent:
    return TranscriptEvent(
        event_id=f"evt-{segment.segment_id}-{segment.sequence_id}",
        event_type="transcript.segment",
        schema_version="1.0",
        session_id=segment.session_id,
        correlation_id="corr-acc2",
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        producer="transcription",
        payload=segment,
    )


class TestAccumulatorWeek2:
    def test_out_of_order_arrival_is_chronologically_sorted(self) -> None:
        acc = SegmentAccumulator()
        # Segments arrive in reverse order: 3, then 2, then 1
        seg_3 = _make_segment(
            "seg-3", sequence_id=2, start_ms=2000, end_ms=3000, text="three"
        )
        seg_2 = _make_segment(
            "seg-2", sequence_id=1, start_ms=1000, end_ms=2000, text="two"
        )
        seg_1 = _make_segment(
            "seg-1", sequence_id=0, start_ms=0, end_ms=1000, text="one"
        )

        acc.add(seg_3)
        acc.add(seg_2)
        acc.add(seg_1)

        ordered = acc.segments()
        assert [s.segment_id for s in ordered] == ["seg-1", "seg-2", "seg-3"]
        assert acc.text() == "one two three"

    def test_revision_tracking_on_text_changes(self) -> None:
        acc = SegmentAccumulator()
        # Initial interim
        seg_v1 = _make_segment(
            "seg-1", sequence_id=0, start_ms=0, end_ms=500, text="Helo", is_final=False
        )
        assert acc.add(seg_v1) is True
        assert acc.revisions_count("seg-1") == 0

        # Revised interim
        seg_v2 = _make_segment(
            "seg-1", sequence_id=1, start_ms=0, end_ms=800, text="Hello", is_final=False
        )
        assert acc.add(seg_v2) is True
        assert acc.revisions_count("seg-1") == 1
        assert acc.text() == "Hello"

        # Final replacement with expanded text
        seg_v3 = _make_segment(
            "seg-1",
            sequence_id=2,
            start_ms=0,
            end_ms=1000,
            text="Hello world.",
            is_final=True,
        )
        assert acc.add(seg_v3) is True
        assert acc.revisions_count("seg-1") == 2
        assert acc.text() == "Hello world."

    def test_exact_duplicates_are_suppressed_without_revision_increment(self) -> None:
        acc = SegmentAccumulator()
        seg = _make_segment(
            "seg-1",
            sequence_id=0,
            start_ms=0,
            end_ms=1000,
            text="Constant",
            is_final=True,
        )

        assert acc.add(seg) is True
        assert acc.revisions_count("seg-1") == 0

        # Identical duplicate arrives
        assert acc.add(seg) is False
        assert acc.revisions_count("seg-1") == 0
        assert len(acc.segments()) == 1
        assert acc.text() == "Constant"

    def test_stale_interim_update_is_ignored(self) -> None:
        acc = SegmentAccumulator()
        # Newer interim arrives first
        seg_newer = _make_segment(
            "seg-1",
            sequence_id=2,
            start_ms=0,
            end_ms=800,
            text="Current draft",
            is_final=False,
        )
        assert acc.add(seg_newer) is True

        # Out-of-order older interim arrives later
        seg_older = _make_segment(
            "seg-1",
            sequence_id=1,
            start_ms=0,
            end_ms=500,
            text="Old draft",
            is_final=False,
        )
        assert acc.add(seg_older) is False
        assert acc.text() == "Current draft"

    def test_final_cannot_regress_to_interim(self) -> None:
        acc = SegmentAccumulator()
        seg_final = _make_segment(
            "seg-1",
            sequence_id=1,
            start_ms=0,
            end_ms=1000,
            text="Finalized",
            is_final=True,
        )
        acc.add(seg_final)

        # Late interim attempt
        seg_late_interim = _make_segment(
            "seg-1",
            sequence_id=2,
            start_ms=0,
            end_ms=1000,
            text="Late interim",
            is_final=False,
        )
        assert acc.add(seg_late_interim) is False
        assert acc.text() == "Finalized"
        assert acc.segments()[0].is_final is True

    def test_final_and_interim_getters(self) -> None:
        acc = SegmentAccumulator()
        s1 = _make_segment(
            "seg-1",
            sequence_id=0,
            start_ms=0,
            end_ms=1000,
            text="Final 1",
            is_final=True,
        )
        s2 = _make_segment(
            "seg-2",
            sequence_id=1,
            start_ms=1000,
            end_ms=1500,
            text="Interim 2",
            is_final=False,
        )
        s3 = _make_segment(
            "seg-3",
            sequence_id=2,
            start_ms=1500,
            end_ms=2500,
            text="Final 3",
            is_final=True,
        )

        acc.add(s1)
        acc.add(s2)
        acc.add(s3)

        finals = acc.final_segments()
        interims = acc.interim_segments()
        assert [s.segment_id for s in finals] == ["seg-1", "seg-3"]
        assert [s.segment_id for s in interims] == ["seg-2"]

    def test_gaps_detection_between_segments(self) -> None:
        acc = SegmentAccumulator()
        # Seg 1: 0ms..1000ms
        s1 = _make_segment(
            "seg-1", sequence_id=0, start_ms=0, end_ms=1000, text="Part 1"
        )
        # Seg 2: 1500ms..2500ms (500ms gap!)
        s2 = _make_segment(
            "seg-2", sequence_id=1, start_ms=1500, end_ms=2500, text="Part 2"
        )
        # Seg 3: 2500ms..3000ms (contiguous, 0ms gap)
        s3 = _make_segment(
            "seg-3", sequence_id=2, start_ms=2500, end_ms=3000, text="Part 3"
        )

        acc.add(s1)
        acc.add(s2)
        acc.add(s3)

        all_gaps = acc.gaps()
        assert all_gaps == [(1000, 1500)]

        # With min_gap_ms threshold
        assert acc.gaps(min_gap_ms=600) == []
        assert acc.gaps(min_gap_ms=400) == [(1000, 1500)]

        with pytest.raises(ValueError, match="nonnegative"):
            acc.gaps(min_gap_ms=-10)

    def test_gaps_with_nested_and_overlapping_segments(self) -> None:
        acc = SegmentAccumulator()
        s1 = _make_segment("seg-1", sequence_id=0, start_ms=0, end_ms=3000, text="A")
        s2 = _make_segment("seg-2", sequence_id=1, start_ms=500, end_ms=1000, text="B")
        s3 = _make_segment("seg-3", sequence_id=2, start_ms=2000, end_ms=2500, text="C")
        acc.add(s1)
        acc.add(s2)
        acc.add(s3)
        assert acc.gaps() == []

    def test_accepts_both_event_and_segment(self) -> None:
        acc = SegmentAccumulator()
        seg1 = _make_segment(
            "seg-1", sequence_id=0, start_ms=0, end_ms=1000, text="Via segment"
        )
        event2 = _make_event(
            _make_segment(
                "seg-2", sequence_id=1, start_ms=1000, end_ms=2000, text="Via event"
            )
        )

        assert acc.add(seg1) is True
        assert acc.add(event2) is True
        assert acc.text() == "Via segment Via event"

    def test_error_events_ignored(self) -> None:
        acc = SegmentAccumulator()
        err_envelope = ErrorEnvelope(
            code="TRANSCRIPTION_ERROR",
            message_safe_for_user="Error occurred",
            retryable=False,
            correlation_id="c1",
        )
        err_event = TranscriptEvent(
            event_id="evt-err-1",
            event_type="transcript.error",
            schema_version="1.0",
            session_id="sess-acc2",
            correlation_id="c1",
            timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            producer="transcription",
            payload=err_envelope,
        )
        assert acc.add(err_event) is False
        assert acc.segments() == []

    def test_mixed_sessions_rejected(self) -> None:
        acc = SegmentAccumulator()
        acc.add(_make_segment("seg-1", session_id="session-A"))
        with pytest.raises(
            ValueError, match="Cannot add event with session_id 'session-B'"
        ):
            acc.add(_make_segment("seg-2", session_id="session-B"))

    def test_invalid_type_raises_type_error(self) -> None:
        acc = SegmentAccumulator()
        with pytest.raises(
            TypeError, match="instance of TranscriptEvent or TranscriptSegment"
        ):
            acc.add(12345)  # type: ignore

    def test_clear_resets_revisions_and_session(self) -> None:
        acc = SegmentAccumulator()
        acc.add(_make_segment("seg-1", sequence_id=0, text="First"))
        acc.add(_make_segment("seg-1", sequence_id=1, text="Second"))
        assert acc.revisions_count("seg-1") == 1

        acc.clear()
        assert acc.session_id is None
        assert acc.segments() == []
        assert acc.revisions_count("seg-1") == 0
