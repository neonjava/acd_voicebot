"""Transcription orchestrator: chunks, preprocessing, adapter, accumulator."""

from collections.abc import Callable, Sequence
from datetime import datetime

from app.contracts.audio import AudioChunk, SpeechEvent
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
        """Cancel transcription for a session, emitting no further events."""
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a nonempty string")
        self._cancelled_sessions.add(session_id)
        self.adapter.cancel(session_id)

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

        if session_id in self._cancelled_sessions:
            return []

        if not chunks:
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

        # Ingest successful segment events into accumulator
        for evt in events:
            if evt.event_type == "transcript.segment":
                self.accumulator.add(evt)

        # Publish to external session event stream if sink is configured
        if self.event_sink is not None:
            for evt in events:
                self.event_sink(session_id, evt)

        return events

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
        """Transcribe chunks between W1 speech_start and speech_end as one utterance."""
        if session_id in self._cancelled_sessions:
            return []

        start_events = [e for e in speech_events if e.kind == "speech_start"]
        end_events = [e for e in speech_events if e.kind == "speech_end"]

        if not start_events or not end_events:
            return []

        utterance_start_ms = start_events[0].at_ms
        utterance_end_ms = end_events[-1].at_ms

        # Filter chunks bounded by speech_start and speech_end
        utterance_chunks = [
            c
            for c in chunks
            if c.start_ms >= utterance_start_ms
            and (c.start_ms + c.duration_ms) <= utterance_end_ms + 40
        ]

        if not utterance_chunks:
            return []

        return self.process_chunks(
            utterance_chunks,
            session_id=session_id,
            correlation_id=correlation_id,
            timestamp=timestamp,
            preprocess=preprocess,
        )

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

    def reset(self) -> None:
        """Clear the accumulator and reset session state."""
        self.accumulator.clear()
        self._batch_counter = 0
        self._cancelled_sessions.clear()
