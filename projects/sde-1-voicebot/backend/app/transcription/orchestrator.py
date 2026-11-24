"""Transcription orchestrator: chunks, preprocessing, adapter, accumulator."""

import uuid
from collections.abc import Callable, Sequence
from datetime import datetime

from app.contracts.audio import AudioChunk, SpeechEvent
from app.contracts.common import ErrorEnvelope
from app.contracts.transcription import TranscriptEvent, TranscriptSegment
from app.transcription.accumulator import SegmentAccumulator
from app.transcription.adapter import TranscriptionAdapter
from app.transcription.config import TranscriptionConfig
from app.transcription.faster_whisper import FasterWhisperAdapter
from app.transcription.mock import FakeTranscriber
from app.transcription.preprocessing import AudioPreprocessor
from app.transcription.retry import RetryPolicy


class TranscriptionOrchestrator:
    """Orchestrates end-to-end transcription pipeline.

    - Consumes W1 AudioChunk objects and SpeechEvent boundaries.
    - Applies optional amplitude normalization and preprocessing.
    - Executes transcription with bounded retries and timeout handling.
    - Supports real local faster-whisper with automatic fallback to mock.
    - Feeds results into SegmentAccumulator for chronological ordering and revisions.
    - Emits typed TranscriptEvent objects and optionally publishes to W5 event stream.
    """

    def __init__(
        self,
        *,
        adapter: TranscriptionAdapter | None = None,
        config: TranscriptionConfig | None = None,
        preprocessor: AudioPreprocessor | None = None,
        retry_policy: RetryPolicy | None = None,
        accumulator: SegmentAccumulator | None = None,
        event_sink: Callable[[str, TranscriptEvent], None] | None = None,
    ) -> None:
        self.config = config if config is not None else TranscriptionConfig.from_env()

        if adapter is not None:
            self.adapter = adapter
        elif self.config.provider == "faster_whisper":
            self.adapter = FasterWhisperAdapter(config=self.config)
        else:
            self.adapter = FakeTranscriber()

        self.preprocessor = (
            preprocessor if preprocessor is not None else AudioPreprocessor()
        )
        self.retry_policy = retry_policy if retry_policy is not None else RetryPolicy()
        self.accumulator = (
            accumulator
            if accumulator is not None
            else SegmentAccumulator(
                confidence_threshold=self.config.confidence_threshold
            )
        )
        self.event_sink = event_sink
        self._batch_counter = 0
        self._cancelled_sessions: set[str] = set()

    def health(self) -> str:
        """Return transcription provider health."""
        return self.adapter.health()

    def cancel(self, session_id: str) -> None:
        """Cancel the current utterance of a session, emitting no events for it.

        The cancellation applies to the utterance in flight, or to the next one
        if nothing is running. Once that utterance is dropped, the session
        transcribes normally again.
        """
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a nonempty string")
        self._cancelled_sessions.add(session_id)
        self.adapter.cancel(session_id)

    def _consume_cancellation(self, session_id: str) -> bool:
        """Drop the cancelled utterance and clear the flag for the next one."""
        if session_id not in self._cancelled_sessions:
            return False
        self._cancelled_sessions.discard(session_id)
        clear = getattr(self.adapter, "clear_cancellation", None)
        if not callable(clear):
            clear = getattr(self.adapter, "reset", None)
        if callable(clear):
            clear(session_id)
        return True

    def process_chunks(
        self,
        chunks: Sequence[AudioChunk],
        *,
        session_id: str,
        correlation_id: str,
        timestamp: datetime,
        preprocess: bool = True,
    ) -> list[TranscriptEvent]:
        """Process incoming audio chunks into validated transcript events.

        1. Check cancellation.
        2. Preprocess chunks (amplitude normalization) if enabled.
        3. Invoke adapter with bounded retry policy.
        4. Accumulate valid transcript segments.
        5. Publish to session event sink if configured.
        6. Return emitted events.
        """
        # Validate identifiers
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a nonempty string")
        if not isinstance(correlation_id, str) or not correlation_id.strip():
            raise ValueError("correlation_id must be a nonempty string")

        if not chunks:
            return []

        if self._consume_cancellation(session_id):
            return []

        # Optional preprocessing
        effective_chunks = chunks
        if preprocess and self.preprocessor is not None:
            effective_chunks = self.preprocessor.process_chunks(chunks)

        self._batch_counter += 1

        # Invoke adapter with retry policy
        events, _ = self.retry_policy.execute_with_retry(
            lambda: self.adapter.transcribe(
                effective_chunks,
                session_id=session_id,
                correlation_id=correlation_id,
                timestamp=timestamp,
            ),
            session_id=session_id,
            correlation_id=correlation_id,
            timestamp=timestamp,
            batch_id=self._batch_counter,
        )

        # A cancel that arrived while the adapter was running drops this utterance
        if self._consume_cancellation(session_id):
            return []

        # Ingest successful segment events into accumulator
        processed_events: list[TranscriptEvent] = []
        for evt in events:
            if evt.event_type == "transcript.segment":
                seg = evt.payload
                # Keep low-confidence segments interim (not final)
                if self.accumulator.is_low_confidence(seg) and seg.is_final:
                    seg = seg.model_copy(update={"is_final": False})
                    evt = evt.model_copy(update={"payload": seg})
                self.accumulator.add(evt)
            processed_events.append(evt)

        # Publish to external session event stream if sink is configured
        if self.event_sink is not None:
            for evt in processed_events:
                self.event_sink(session_id, evt)

        return processed_events

    def process_speech_session(
        self,
        speech_events: Sequence[SpeechEvent],
        chunks: Sequence[AudioChunk],
        *,
        session_id: str,
        correlation_id: str,
        timestamp: datetime,
        preprocess: bool = True,
    ) -> list[TranscriptEvent]:
        """Transcribe chunks between W1 speech_start and speech_end boundaries.

        - Rejects speech events belonging to mismatched sessions.
        - Identifies each distinct (speech_start, speech_end) utterance without merging.
        """
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a nonempty string")
        if not isinstance(correlation_id, str) or not correlation_id.strip():
            raise ValueError("correlation_id must be a nonempty string")

        # Validate that all speech events belong strictly to the target session
        for e in speech_events:
            if e.session_id != session_id:
                raise ValueError(
                    f"Cannot process speech event with session_id '{e.session_id}' "
                    f"in session '{session_id}'"
                )

        # Pair speech_start and speech_end events to process each utterance separately
        utterance_intervals: list[tuple[int, int]] = []
        boundary_events: list[TranscriptEvent] = []
        current_start: int | None = None

        for e in sorted(speech_events, key=lambda ev: (ev.at_ms, ev.sequence_id)):
            if e.kind == "speech_start":
                if current_start is not None:
                    # Duplicate speech_start before speech_end: ignore duplicate start
                    err_env = ErrorEnvelope(
                        code="TRANSCRIPTION_UNMATCHED_SPEECH_BOUNDARY",
                        message_safe_for_user=(
                            "Duplicate speech_start received before speech_end."
                        ),
                        retryable=False,
                        correlation_id=correlation_id,
                        details_redacted={
                            "session_id": session_id,
                            "reason": "duplicate_speech_start",
                            "at_ms": str(e.at_ms),
                        },
                    )
                    boundary_events.append(
                        TranscriptEvent(
                            event_id=(
                                f"event-transcript-err-{session_id}-"
                                f"{uuid.uuid4().hex[:8]}"
                            ),
                            event_type="transcript.error",
                            schema_version="1.0",
                            session_id=session_id,
                            correlation_id=correlation_id,
                            timestamp=timestamp,
                            producer="transcription",
                            payload=err_env,
                        )
                    )
                else:
                    current_start = e.at_ms
            elif e.kind == "speech_end":
                if current_start is not None:
                    utterance_intervals.append((current_start, e.at_ms))
                    current_start = None
                else:
                    err_env = ErrorEnvelope(
                        code="TRANSCRIPTION_UNMATCHED_SPEECH_BOUNDARY",
                        message_safe_for_user=(
                            "speech_end received without matching speech_start."
                        ),
                        retryable=False,
                        correlation_id=correlation_id,
                        details_redacted={
                            "session_id": session_id,
                            "reason": "unmatched_speech_end",
                            "at_ms": str(e.at_ms),
                        },
                    )
                    boundary_events.append(
                        TranscriptEvent(
                            event_id=(
                                f"event-transcript-err-{session_id}-"
                                f"{uuid.uuid4().hex[:8]}"
                            ),
                            event_type="transcript.error",
                            schema_version="1.0",
                            session_id=session_id,
                            correlation_id=correlation_id,
                            timestamp=timestamp,
                            producer="transcription",
                            payload=err_env,
                        )
                    )

        if current_start is not None:
            # speech_start with no speech_end: emit normalized error event
            err_env = ErrorEnvelope(
                code="TRANSCRIPTION_UNMATCHED_SPEECH_BOUNDARY",
                message_safe_for_user=(
                    "speech_start received without matching speech_end."
                ),
                retryable=False,
                correlation_id=correlation_id,
                details_redacted={
                    "session_id": session_id,
                    "reason": "unclosed_speech_start",
                    "at_ms": str(current_start),
                },
            )
            boundary_events.append(
                TranscriptEvent(
                    event_id=(
                        f"event-transcript-err-{session_id}-{uuid.uuid4().hex[:8]}"
                    ),
                    event_type="transcript.error",
                    schema_version="1.0",
                    session_id=session_id,
                    correlation_id=correlation_id,
                    timestamp=timestamp,
                    producer="transcription",
                    payload=err_env,
                )
            )

        # Publish boundary error events to event sink if configured
        if self.event_sink is not None:
            for evt in boundary_events:
                self.event_sink(session_id, evt)

        if not utterance_intervals:
            return boundary_events

        all_events: list[TranscriptEvent] = []
        for start_ms, end_ms in utterance_intervals:
            utterance_chunks = [
                c
                for c in chunks
                if c.start_ms < end_ms and (c.start_ms + c.duration_ms) > start_ms
            ]
            if utterance_chunks:
                evts = self.process_chunks(
                    utterance_chunks,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    timestamp=timestamp,
                    preprocess=preprocess,
                )
                all_events.extend(evts)

        return [*all_events, *boundary_events]

    def ingest_event(self, event: TranscriptEvent) -> bool:
        """Directly add a transcript event to the accumulator."""
        return self.accumulator.add(event)

    def get_transcript_text(self, *, include_low_confidence: bool = True) -> str:
        """Return the combined text of all accumulated segments in order."""
        return self.accumulator.text(include_low_confidence=include_low_confidence)

    def get_final_text(self, *, include_low_confidence: bool = False) -> str:
        """Return text of finalized segments, excluding low-confidence by default."""
        return self.accumulator.final_text(
            include_low_confidence=include_low_confidence
        )

    def get_segments(self) -> list[TranscriptSegment]:
        """Return all accumulated segments in chronological order."""
        return self.accumulator.segments()

    def get_final_segments(
        self, *, include_low_confidence: bool = False
    ) -> list[TranscriptSegment]:
        """Return only finalized segments (excluding low-confidence by default)."""
        return self.accumulator.final_segments(
            include_low_confidence=include_low_confidence
        )

    def get_low_confidence_segments(self) -> list[TranscriptSegment]:
        """Return segments flagged below the confidence threshold."""
        return self.accumulator.low_confidence_segments()

    def get_revisions(self, segment_id: str) -> int:
        """Return the number of revisions recorded for a segment ID."""
        return self.accumulator.revisions_count(segment_id)

    def get_gaps(self, min_gap_ms: int = 0) -> list[tuple[int, int]]:
        """Return detected chronological gaps between segments."""
        return self.accumulator.gaps(min_gap_ms)

    def reset(self, session_id: str | None = None) -> None:
        """Clear the accumulator and reset session state in orchestrator and adapter."""
        self.accumulator.clear()
        self._batch_counter = 0
        if session_id:
            self._cancelled_sessions.discard(session_id)
        else:
            self._cancelled_sessions.clear()
        if hasattr(self.adapter, "reset"):
            self.adapter.reset(session_id)
