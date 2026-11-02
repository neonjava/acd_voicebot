"""Deterministic energy-based mock VAD over validated AudioChunk values."""

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from app.contracts.audio import AudioChunk


@dataclass(frozen=True)
class SpeechSpan:
    session_id: str
    start_ms: int
    end_ms: int


class VoiceActivityDetector(Protocol):
    def detect(self, chunks: Sequence[AudioChunk]) -> list[SpeechSpan]: ...


class MockVAD:
    """Mark contiguous above-threshold chunks as speech after a minimum duration."""

    def __init__(self, *, threshold: float = 0.1, min_speech_ms: int = 40) -> None:
        if type(threshold) not in (int, float) or not isfinite(threshold):
            raise ValueError("threshold must be a finite number")
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between zero and one")
        if type(min_speech_ms) is not int or min_speech_ms <= 0:
            raise ValueError("min_speech_ms must be a positive integer")
        self.threshold = float(threshold)
        self.min_speech_ms = min_speech_ms

    def detect(self, chunks: Sequence[AudioChunk]) -> list[SpeechSpan]:
        spans: list[SpeechSpan] = []
        session_id: str | None = None
        previous_sequence: int | None = None
        previous_end: int | None = None
        active_start: int | None = None
        active_end: int | None = None

        def finish() -> None:
            nonlocal active_start, active_end
            if (
                active_start is not None
                and active_end is not None
                and active_end - active_start >= self.min_speech_ms
            ):
                assert session_id is not None
                spans.append(SpeechSpan(session_id, active_start, active_end))
            active_start = None
            active_end = None

        for chunk in chunks:
            if not isinstance(chunk, AudioChunk):
                raise TypeError("chunks must contain AudioChunk values")
            if session_id is None:
                session_id = chunk.session_id
            elif chunk.session_id != session_id:
                raise ValueError("VAD cannot mix sessions")
            if previous_sequence is not None:
                if (
                    chunk.sequence_id <= previous_sequence
                    or chunk.start_ms < previous_end
                ):
                    raise ValueError("VAD chunks must be ordered and nonoverlapping")
                if (
                    chunk.sequence_id != previous_sequence + 1
                    or chunk.start_ms != previous_end
                ):
                    finish()

            samples = len(chunk.pcm) // 2
            energy = sum(
                abs(int.from_bytes(chunk.pcm[i : i + 2], "little", signed=True))
                for i in range(0, len(chunk.pcm), 2)
            ) / (samples * 32768)
            if energy >= self.threshold:
                if active_start is None:
                    active_start = chunk.start_ms
                active_end = chunk.start_ms + chunk.duration_ms
            else:
                finish()
            previous_sequence = chunk.sequence_id
            previous_end = chunk.start_ms + chunk.duration_ms
        finish()
        return spans
