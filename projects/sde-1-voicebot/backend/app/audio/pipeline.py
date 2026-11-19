"""Speech-event pipeline: wake gate, VAD spans, late-chunk guard, W2 handoff."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.audio.config import AudioConfig, create_vad, create_wake_word_detector
from app.audio.vad import SpeechSpan, VoiceActivityDetector
from app.audio.wake import WakeDetection, WakeWordDetector
from app.contracts.audio import AudioChunk, SpeechEvent
from app.contracts.common import EventEnvelope
from app.contracts.transcription import TranscriptEvent


class TranscriptionSink(Protocol):
    """Minimal W2 transcription interface satisfied by TranscriptionOrchestrator."""

    def process_chunks(
        self,
        chunks: Sequence[AudioChunk],
        *,
        session_id: str,
        correlation_id: str,
        timestamp: datetime,
        preprocess: bool = True,
    ) -> list[TranscriptEvent]: ...


def spans_to_speech_events(
    spans: Sequence[SpeechSpan],
    *,
    session_id: str,
    correlation_id: str,
    start_sequence_id: int = 0,
) -> list[SpeechEvent]:
    """Convert VAD SpeechSpan items into ordered speech_start/speech_end events."""
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id must be a nonempty string")
    if not isinstance(correlation_id, str) or not correlation_id.strip():
        raise ValueError("correlation_id must be a nonempty string")
    if type(start_sequence_id) is not int or start_sequence_id < 0:
        raise ValueError("start_sequence_id must be a nonnegative integer")

    events: list[SpeechEvent] = []
    seq = start_sequence_id
    for span in spans:
        if span.session_id != session_id:
            raise ValueError("SpeechSpan session_id does not match session_id")
        events.append(
            SpeechEvent(
                kind="speech_start",
                session_id=session_id,
                correlation_id=correlation_id,
                sequence_id=seq,
                at_ms=span.start_ms,
            )
        )
        events.append(
            SpeechEvent(
                kind="speech_end",
                session_id=session_id,
                correlation_id=correlation_id,
                sequence_id=seq + 1,
                at_ms=span.end_ms,
            )
        )
        seq += 2
    return events


def to_speech_envelope(
    event: SpeechEvent, *, event_id: str, timestamp: datetime
) -> EventEnvelope[SpeechEvent]:
    """Wrap a SpeechEvent in the Week 3 EventEnvelope contract."""
    return EventEnvelope[SpeechEvent](
        event_id=event_id,
        event_type="audio.speech",
        session_id=event.session_id,
        correlation_id=event.correlation_id,
        timestamp=timestamp,
        producer="audio",
        payload=event,
    )


@dataclass(frozen=True)
class PipelineStepResult:
    """Outputs produced by feeding one or more chunks into SpeechPipeline."""

    speech_events: list[SpeechEvent] = field(default_factory=list)
    utterance_chunks: list[AudioChunk] = field(default_factory=list)
    transcript_events: list[TranscriptEvent] = field(default_factory=list)


class SpeechPipeline:
    """Coordinate wake gating, VAD SpeechEvents, and W2 transcription handoff."""

    def __init__(
        self,
        *,
        session_id: str,
        correlation_id: str,
        config: AudioConfig | None = None,
        wake_detector: WakeWordDetector | None = None,
        vad: VoiceActivityDetector | None = None,
        orchestrator: TranscriptionSink | None = None,
    ) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a nonempty string")
        if not isinstance(correlation_id, str) or not correlation_id.strip():
            raise ValueError("correlation_id must be a nonempty string")

        self.session_id = session_id
        self.correlation_id = correlation_id
        self.config = config if config is not None else AudioConfig()
        self.wake_detector = (
            wake_detector
            if wake_detector is not None
            else create_wake_word_detector(self.config)
        )
        self.vad = vad if vad is not None else create_vad(self.config)
        self.orchestrator = orchestrator

        self._next_speech_seq = 0
        self._listening = not self.config.wake_required
        # A wake fires only after the detector has seen a below-threshold chunk,
        # so one spoken wake word (whose score stays high for several frames)
        # can never trigger twice.
        self._wake_armed = True
        self._silence_since_ms: int | None = None
        self._vad_window: list[AudioChunk] = []
        self._active_span_start: int | None = None
        self._active_span_end: int | None = None
        self._last_chunk_sequence_id: int | None = None
        self._last_chunk_end_ms: int | None = None

        self.cancelled = False
        self.late_chunks = 0
        self.silence_timeouts = 0
        self.events: list[SpeechEvent] = []
        self.transcript_events: list[TranscriptEvent] = []

    @property
    def listening(self) -> bool:
        return self._listening

    def _alloc_seq(self) -> int:
        seq = self._next_speech_seq
        self._next_speech_seq += 1
        return seq

    def _record_event(self, event: SpeechEvent, out_events: list[SpeechEvent]) -> None:
        self.events.append(event)
        out_events.append(event)

    def _handoff_utterance(
        self,
        utterance: list[AudioChunk],
        *,
        timestamp: datetime,
        out_chunks: list[AudioChunk],
        out_transcripts: list[TranscriptEvent],
    ) -> None:
        if not utterance:
            return
        out_chunks.extend(utterance)
        if self.orchestrator is not None:
            produced = self.orchestrator.process_chunks(
                utterance,
                session_id=self.session_id,
                correlation_id=self.correlation_id,
                timestamp=timestamp,
            )
            self.transcript_events.extend(produced)
            out_transcripts.extend(produced)

    def _close_active_span(
        self,
        *,
        timestamp: datetime,
        out_events: list[SpeechEvent],
        out_chunks: list[AudioChunk],
        out_transcripts: list[TranscriptEvent],
        keep_listening: bool = False,
    ) -> None:
        if self._active_span_start is None or self._active_span_end is None:
            return
        span_start = self._active_span_start
        span_end = self._active_span_end
        end_event = SpeechEvent(
            kind="speech_end",
            session_id=self.session_id,
            correlation_id=self.correlation_id,
            sequence_id=self._alloc_seq(),
            at_ms=span_end,
        )
        self._record_event(end_event, out_events)
        utterance = [
            item
            for item in self._vad_window
            if (
                item.start_ms >= span_start
                and item.start_ms + item.duration_ms <= span_end
            )
        ]
        self._handoff_utterance(
            utterance,
            timestamp=timestamp,
            out_chunks=out_chunks,
            out_transcripts=out_transcripts,
        )
        self._active_span_start = None
        self._active_span_end = None
        self._vad_window.clear()
        if self.config.wake_required and not keep_listening:
            self._listening = False
            self._silence_since_ms = None
        else:
            self._silence_since_ms = span_end

    def _handle_wake_gate(
        self,
        chunk: AudioChunk,
        detection: WakeDetection | None,
        out_events: list[SpeechEvent],
    ) -> None:
        if detection is None or not self._wake_armed:
            return
        self._wake_armed = False
        wake_event = SpeechEvent(
            kind="wake",
            session_id=self.session_id,
            correlation_id=self.correlation_id,
            sequence_id=self._alloc_seq(),
            at_ms=detection.at_ms,
            wake_word=detection.wake_word,
            score=detection.score,
        )
        self._record_event(wake_event, out_events)
        self._listening = True
        self._silence_since_ms = chunk.start_ms + chunk.duration_ms
        self._vad_window.clear()
        self._active_span_start = None
        self._active_span_end = None

    def process_chunk(
        self, chunk: AudioChunk, *, timestamp: datetime
    ) -> PipelineStepResult:
        """Process one AudioChunk through wake gating, VAD, and W2 handoff."""
        if not isinstance(chunk, AudioChunk):
            raise TypeError("chunk must be an AudioChunk")
        if chunk.session_id != self.session_id:
            raise ValueError("cannot mix sessions in SpeechPipeline")
        if self.cancelled:
            return PipelineStepResult()

        if self._last_chunk_sequence_id is not None and (
            chunk.sequence_id <= self._last_chunk_sequence_id
            or chunk.start_ms < (self._last_chunk_end_ms or 0)
        ):
            self.late_chunks += 1
            return PipelineStepResult()

        self._last_chunk_sequence_id = chunk.sequence_id
        chunk_end_ms = chunk.start_ms + chunk.duration_ms
        self._last_chunk_end_ms = chunk_end_ms

        out_events: list[SpeechEvent] = []
        out_chunks: list[AudioChunk] = []
        out_transcripts: list[TranscriptEvent] = []

        # Feed the wake detector every chunk, even while listening: streaming
        # models such as openWakeWord need continuous audio, and this is how a
        # below-threshold chunk re-arms the gate.
        detection: WakeDetection | None = None
        if self.config.wake_required:
            detection = self.wake_detector.detect(chunk)
            if detection is None:
                self._wake_armed = True

        if self.config.wake_required and not self._listening:
            self._handle_wake_gate(chunk, detection, out_events)
            return PipelineStepResult(
                speech_events=out_events,
                utterance_chunks=out_chunks,
                transcript_events=out_transcripts,
            )

        # A sequence or time gap ends any in-progress speech run cleanly.
        if self._vad_window:
            prev = self._vad_window[-1]
            has_gap = (
                chunk.sequence_id != prev.sequence_id + 1
                or chunk.start_ms != prev.start_ms + prev.duration_ms
            )
            if has_gap:
                if self._active_span_start is not None:
                    self._close_active_span(
                        timestamp=timestamp,
                        out_events=out_events,
                        out_chunks=out_chunks,
                        out_transcripts=out_transcripts,
                    )
                else:
                    self._vad_window.clear()

                if self.config.wake_required and not self._listening:
                    self._handle_wake_gate(chunk, detection, out_events)
                    return PipelineStepResult(
                        speech_events=out_events,
                        utterance_chunks=out_chunks,
                        transcript_events=out_transcripts,
                    )

        self._vad_window.append(chunk)
        spans = self.vad.detect(self._vad_window)

        if not spans:
            if self._active_span_start is None:
                # Keep only enough idle audio for the VAD minimum, so long
                # silences never grow the window or the VAD cost.
                min_speech_ms = getattr(
                    self.vad, "min_speech_ms", self.config.vad_min_speech_ms
                )
                keep = max(1, -(-min_speech_ms // max(chunk.duration_ms, 1)))
                del self._vad_window[:-keep]
            if (
                self.config.wake_required
                and self._listening
                and self._active_span_start is None
                and self._silence_since_ms is not None
                and chunk_end_ms - self._silence_since_ms
                >= self.config.silence_timeout_ms
            ):
                self._listening = False
                self._silence_since_ms = None
                self._vad_window.clear()
                self.silence_timeouts += 1
            return PipelineStepResult(
                speech_events=out_events,
                utterance_chunks=out_chunks,
                transcript_events=out_transcripts,
            )

        # Short pauses between words produce several VAD spans; they belong to
        # one utterance until the silence after the last span is long enough.
        span_start = spans[0].start_ms
        span_end = spans[-1].end_ms
        if self._active_span_start is None:
            self._active_span_start = span_start
            self._active_span_end = span_end
            start_event = SpeechEvent(
                kind="speech_start",
                session_id=self.session_id,
                correlation_id=self.correlation_id,
                sequence_id=self._alloc_seq(),
                at_ms=span_start,
            )
            self._record_event(start_event, out_events)
        else:
            self._active_span_end = span_end

        if chunk_end_ms - span_start >= self.config.max_utterance_ms:
            # Very long speech is split; listening stays open so the rest of
            # the sentence becomes the next utterance instead of being lost.
            self._active_span_end = chunk_end_ms
            self._close_active_span(
                timestamp=timestamp,
                out_events=out_events,
                out_chunks=out_chunks,
                out_transcripts=out_transcripts,
                keep_listening=True,
            )
        elif chunk_end_ms - span_end >= self.config.speech_end_silence_ms:
            self._close_active_span(
                timestamp=timestamp,
                out_events=out_events,
                out_chunks=out_chunks,
                out_transcripts=out_transcripts,
            )

        return PipelineStepResult(
            speech_events=out_events,
            utterance_chunks=out_chunks,
            transcript_events=out_transcripts,
        )

    def process_chunks(
        self,
        chunks: Sequence[AudioChunk],
        *,
        timestamp: datetime,
        final: bool = False,
    ) -> PipelineStepResult:
        """Process a sequence of AudioChunk values and optionally flush at the end."""
        all_events: list[SpeechEvent] = []
        all_chunks: list[AudioChunk] = []
        all_transcripts: list[TranscriptEvent] = []
        for chunk in chunks:
            step = self.process_chunk(chunk, timestamp=timestamp)
            all_events.extend(step.speech_events)
            all_chunks.extend(step.utterance_chunks)
            all_transcripts.extend(step.transcript_events)
        if final:
            flushed = self.flush(timestamp=timestamp)
            all_events.extend(flushed.speech_events)
            all_chunks.extend(flushed.utterance_chunks)
            all_transcripts.extend(flushed.transcript_events)
        return PipelineStepResult(
            speech_events=all_events,
            utterance_chunks=all_chunks,
            transcript_events=all_transcripts,
        )

    def flush(self, *, timestamp: datetime) -> PipelineStepResult:
        """Close any open speech span at end of stream and hand off its chunks."""
        if self.cancelled:
            return PipelineStepResult()
        out_events: list[SpeechEvent] = []
        out_chunks: list[AudioChunk] = []
        out_transcripts: list[TranscriptEvent] = []
        self._close_active_span(
            timestamp=timestamp,
            out_events=out_events,
            out_chunks=out_chunks,
            out_transcripts=out_transcripts,
        )
        return PipelineStepResult(
            speech_events=out_events,
            utterance_chunks=out_chunks,
            transcript_events=out_transcripts,
        )

    def cancel(self) -> None:
        """Cancel pipeline processing and discard buffered state without emitting."""
        self.cancelled = True
        self._listening = False
        self._silence_since_ms = None
        self._vad_window.clear()
        self._active_span_start = None
        self._active_span_end = None
