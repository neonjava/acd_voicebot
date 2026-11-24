"""Voice activity detection: deterministic energy mock and real Silero VAD."""

import array
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

            if self._is_speech(chunk):
                if active_start is None:
                    active_start = chunk.start_ms
                active_end = chunk.start_ms + chunk.duration_ms
            else:
                finish()
            previous_sequence = chunk.sequence_id
            previous_end = chunk.start_ms + chunk.duration_ms
        finish()
        return spans

    def _is_speech(self, chunk: AudioChunk) -> bool:
        samples = len(chunk.pcm) // 2
        energy = sum(
            abs(int.from_bytes(chunk.pcm[i : i + 2], "little", signed=True))
            for i in range(0, len(chunk.pcm), 2)
        ) / (samples * 32768)
        return energy >= self.threshold


class SileroVAD(MockVAD):
    """Real speech detector: Silero VAD (shipped with openwakeword, audio extra).

    Silero is a streaming model, so each chunk is scored exactly once, in order,
    and the score is cached by sequence ID; ``detect`` may then be called on any
    window of already-seen chunks. Span building is shared with ``MockVAD``.
    """

    def __init__(
        self,
        *,
        threshold: float = 0.5,
        min_speech_ms: int = 100,
        model: object | None = None,
        cache_size: int = 2000,
    ) -> None:
        super().__init__(threshold=threshold, min_speech_ms=min_speech_ms)
        if type(cache_size) is not int or cache_size <= 0:
            raise ValueError("cache_size must be a positive integer")
        self._model = model
        self._cache_size = cache_size
        self._scores: dict[int, float] = {}
        self._window_floor = 0
        self._session_id: str | None = None

    def _ensure_model(self) -> object:
        if self._model is not None:
            return self._model
        try:
            from openwakeword.vad import VAD
        except ImportError as exc:
            from app.audio.device import AudioDeviceError

            raise AudioDeviceError(
                "AUDIO_DEPENDENCY_MISSING",
                "Real voice activity detection requires the audio extra.",
            ) from exc
        try:
            self._model = VAD()
        except Exception as exc:
            from app.audio.device import AudioDeviceError

            raise AudioDeviceError(
                "AUDIO_VAD_MODEL_UNAVAILABLE",
                "The voice activity model could not be loaded.",
            ) from exc
        return self._model

    def speech_probability(self, chunk: AudioChunk) -> float:
        """Return the cached Silero speech probability for one chunk."""
        if chunk.session_id != self._session_id:
            self._start_session(chunk.session_id)
        cached = self._scores.get(chunk.sequence_id)
        if cached is not None:
            return cached
        model = self._ensure_model()
        try:
            import numpy as np

            samples: object = np.frombuffer(chunk.pcm, dtype=np.int16)
        except ImportError:  # only an injected test model runs without numpy
            pcm_samples = array.array("h")
            pcm_samples.frombytes(chunk.pcm)
            samples = pcm_samples
        raw = float(model.predict(samples, frame_size=len(chunk.pcm) // 2))  # type: ignore[attr-defined]
        score = max(0.0, min(1.0, raw)) if isfinite(raw) else 0.0
        self._scores[chunk.sequence_id] = score
        if len(self._scores) > self._cache_size:
            # Only drop scores for chunks older than the window being checked;
            # a chunk still in the window must never be scored a second time.
            for old in sorted(self._scores):
                if len(self._scores) <= self._cache_size or old >= self._window_floor:
                    break
                del self._scores[old]
        return score

    def detect(self, chunks: Sequence[AudioChunk]) -> list[SpeechSpan]:
        if chunks:
            self._window_floor = chunks[0].sequence_id
        return super().detect(chunks)

    def _start_session(self, session_id: str) -> None:
        """Sequence IDs restart per session: drop old scores and model state."""
        self._session_id = session_id
        self._scores.clear()
        self._window_floor = 0
        reset = getattr(self._model, "reset_states", None)
        if callable(reset):
            reset()

    def _is_speech(self, chunk: AudioChunk) -> bool:
        return self.speech_probability(chunk) >= self.threshold
