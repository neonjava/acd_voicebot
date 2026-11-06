"""Transcription orchestrator: chunks, preprocessing, adapter, accumulator."""

from collections.abc import Sequence
from datetime import datetime

from app.contracts.audio import AudioChunk
from app.contracts.transcription import TranscriptEvent, TranscriptSegment
from app.transcription.accumulator import SegmentAccumulator
from app.transcription.adapter import TranscriptionAdapter
from app.transcription.mock import FakeTranscriber
from app.transcription.preprocessing import AudioPreprocessor
from app.transcription.retry import RetryPolicy


class TranscriptionOrchestrator:
    """Orchestrates end-to-end transcription pipeline.

    - Consumes W1 AudioChunk objects.
    - Applies optional amplitude normalization and preprocessing.
    - Executes transcription with bounded retries and timeout handling.
    - Feeds results into SegmentAccumulator for chronological ordering.
    - Emits typed TranscriptEvent objects for W5 sessions.
    """

    def __init__(
        self,
        *,
        adapter: TranscriptionAdapter | None = None,
        preprocessor: AudioPreprocessor | None = None,
        retry_policy: RetryPolicy | None = None,
        accumulator: SegmentAccumulator | None = None,
    ) -> None:
        self.adapter = adapter if adapter is not None else FakeTranscriber()
        self.preprocessor = (
            preprocessor if preprocessor is not None else AudioPreprocessor()
        )
        self.retry_policy = retry_policy if retry_policy is not None else RetryPolicy()
        self.accumulator = (
            accumulator if accumulator is not None else SegmentAccumulator()
        )
        self._batch_counter = 0

    def health(self) -> str:
        """Return transcription provider health."""
        return self.adapter.health()

    def cancel(self, session_id: str) -> None:
        """Cancel transcription for a session."""
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

        1. Preprocess chunks (amplitude normalization) if enabled.
        2. Invoke adapter with bounded retry policy.
        3. Accumulate valid transcript segments.
        4. Return emitted events.
        """
        # Validate identifiers
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a nonempty string")
        if not isinstance(correlation_id, str) or not correlation_id.strip():
            raise ValueError("correlation_id must be a nonempty string")

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

        return events

    def ingest_event(self, event: TranscriptEvent) -> bool:
        """Directly add a transcript event to the accumulator."""
        return self.accumulator.add(event)

    def get_transcript_text(self) -> str:
        """Return the combined text of all accumulated segments in order."""
        return self.accumulator.text()

    def get_segments(self) -> list[TranscriptSegment]:
        """Return all accumulated segments in chronological order."""
        return self.accumulator.segments()

    def get_final_segments(self) -> list[TranscriptSegment]:
        """Return only finalized segments (for W3 reasoning context mapping)."""
        return self.accumulator.final_segments()

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
