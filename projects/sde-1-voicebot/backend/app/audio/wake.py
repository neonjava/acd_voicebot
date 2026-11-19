"""Wake-word detection protocol, deterministic mock, and lazy openWakeWord adapter."""

import array
from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from app.audio.chunker import BYTES_PER_MS
from app.audio.device import AudioDeviceError
from app.contracts.audio import AudioChunk

WAKE_MARKER_PATTERN = b"\x4a\x56\x57\x4b"  # "JVWK"
SUB_THRESHOLD_MARKER_PATTERN = b"\x4a\x56\x4c\x4f"  # "JVLO"
_MARKER_SIGNATURE = WAKE_MARKER_PATTERN * 4
_SUB_THRESHOLD_SIGNATURE = SUB_THRESHOLD_MARKER_PATTERN * 4


def _validate_threshold(threshold: float) -> float:
    if type(threshold) not in (int, float) or not isfinite(threshold):
        raise ValueError("threshold must be a finite number")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between zero and one")
    return float(threshold)


def _validate_wake_word(wake_word: str) -> str:
    if not isinstance(wake_word, str) or not wake_word.strip():
        raise ValueError("wake_word must be a nonempty string")
    return wake_word


def make_wake_pcm(*, duration_ms: int = 20, above_threshold: bool = True) -> bytes:
    """Build deterministic 16 kHz mono PCM carrying a synthetic wake marker."""
    if type(duration_ms) is not int or duration_ms <= 0:
        raise ValueError("duration_ms must be a positive integer")
    if type(above_threshold) is not bool:
        raise ValueError("above_threshold must be a boolean")
    total_bytes = duration_ms * BYTES_PER_MS
    pattern = WAKE_MARKER_PATTERN if above_threshold else SUB_THRESHOLD_MARKER_PATTERN
    repeats = (total_bytes // len(pattern)) + 1
    return (pattern * repeats)[:total_bytes]


@dataclass(frozen=True)
class WakeDetection:
    """Result emitted when wake-word score meets or exceeds threshold."""

    wake_word: str
    score: float
    at_ms: int


class WakeWordDetector(Protocol):
    """Protocol for chunk-level wake-word detectors."""

    @property
    def wake_word(self) -> str: ...

    @property
    def threshold(self) -> float: ...

    def detect(self, chunk: AudioChunk) -> WakeDetection | None: ...


class MockWakeWordDetector:
    """Deterministic wake detector triggered by synthetic PCM markers or score map."""

    def __init__(
        self,
        *,
        wake_word: str = "hey_jarvis",
        threshold: float = 0.5,
        score_by_sequence: dict[int, float] | None = None,
    ) -> None:
        self._wake_word = _validate_wake_word(wake_word)
        self._threshold = _validate_threshold(threshold)
        self._score_by_sequence = (
            dict(score_by_sequence) if score_by_sequence is not None else {}
        )
        for seq, val in self._score_by_sequence.items():
            if type(seq) is not int or seq < 0:
                raise ValueError("score_by_sequence keys must be nonnegative integers")
            _validate_threshold(val)

    @property
    def wake_word(self) -> str:
        return self._wake_word

    @property
    def threshold(self) -> float:
        return self._threshold

    def score(self, chunk: AudioChunk) -> float:
        """Return deterministic wake score in [0.0, 1.0] for one validated chunk."""
        if not isinstance(chunk, AudioChunk):
            raise TypeError("chunk must be an AudioChunk")
        if chunk.sequence_id in self._score_by_sequence:
            return self._score_by_sequence[chunk.sequence_id]
        if _MARKER_SIGNATURE in chunk.pcm:
            return 0.95
        if _SUB_THRESHOLD_SIGNATURE in chunk.pcm:
            return 0.3
        return 0.0

    def detect(self, chunk: AudioChunk) -> WakeDetection | None:
        score = self.score(chunk)
        if score < self._threshold:
            return None
        return WakeDetection(
            wake_word=self._wake_word, score=score, at_ms=chunk.start_ms
        )


class OpenWakeWordDetector:
    """Real wake-word detector using openWakeWord with the hey_jarvis ONNX model."""

    def __init__(
        self,
        *,
        wake_word: str = "hey_jarvis",
        threshold: float = 0.5,
        inference_framework: str = "onnx",
        model: object | None = None,
        auto_download: bool = True,
    ) -> None:
        self._wake_word = _validate_wake_word(wake_word)
        self._threshold = _validate_threshold(threshold)
        if inference_framework != "onnx":
            raise ValueError(
                "OpenWakeWordDetector supports only inference_framework='onnx'"
            )
        if type(auto_download) is not bool:
            raise ValueError("auto_download must be a boolean")
        self.inference_framework = inference_framework
        self.auto_download = auto_download
        self._model = model

    @property
    def wake_word(self) -> str:
        return self._wake_word

    @property
    def threshold(self) -> float:
        return self._threshold

    def _ensure_model(self) -> object:
        if self._model is not None:
            return self._model
        try:
            from openwakeword.model import Model
        except ImportError as exc:
            raise AudioDeviceError(
                "AUDIO_DEPENDENCY_MISSING",
                "Wake word detection requires the audio extra.",
            ) from exc
        try:
            self._model = self._load_model(Model)
        except AudioDeviceError:
            raise
        except Exception as exc:
            raise AudioDeviceError(
                "AUDIO_WAKE_MODEL_UNAVAILABLE",
                "The wake word model could not be loaded.",
            ) from exc
        return self._model

    def _load_model(self, model_cls: type) -> object:
        """Load the model, downloading it once if it is not installed yet."""
        try:
            return model_cls(
                wakeword_models=[self._wake_word],
                inference_framework=self.inference_framework,
            )
        except Exception:
            if not self.auto_download:
                raise
        try:
            from openwakeword.utils import download_models
        except ImportError as exc:
            raise AudioDeviceError(
                "AUDIO_WAKE_MODEL_UNAVAILABLE",
                "The wake word model is not installed.",
            ) from exc
        download_models(model_names=[self._wake_word])
        return model_cls(
            wakeword_models=[self._wake_word],
            inference_framework=self.inference_framework,
        )

    def score(self, chunk: AudioChunk) -> float:
        """Score one 16 kHz mono PCM chunk with the ONNX wake-word model."""
        if not isinstance(chunk, AudioChunk):
            raise TypeError("chunk must be an AudioChunk")
        model = self._ensure_model()
        try:
            import numpy as np

            samples: object = np.frombuffer(chunk.pcm, dtype=np.int16)
        except ImportError:
            pcm_samples = array.array("h")
            pcm_samples.frombytes(chunk.pcm)
            samples = pcm_samples

        prediction = model.predict(samples)  # type: ignore[attr-defined]
        if not isinstance(prediction, dict) or not prediction:
            return 0.0
        if self._wake_word in prediction:
            raw = float(prediction[self._wake_word])
        else:
            matching = [
                float(val)
                for key, val in prediction.items()
                if self._wake_word in str(key)
            ]
            if not matching:
                return 0.0
            raw = max(matching)
        if not isfinite(raw):
            return 0.0
        return max(0.0, min(1.0, raw))

    def detect(self, chunk: AudioChunk) -> WakeDetection | None:
        score = self.score(chunk)
        if score < self._threshold:
            return None
        return WakeDetection(
            wake_word=self._wake_word, score=score, at_ms=chunk.start_ms
        )
