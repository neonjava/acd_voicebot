"""Audio contracts shared by the mock source and transcription workstreams."""

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from app.contracts.common import ContractModel, ErrorEnvelope


class AudioFormat(ContractModel):
    """The single PCM format supported in Week 1."""

    sample_rate_hz: Literal[16000] = 16000
    channels: Literal[1] = 1
    encoding: Literal["pcm_s16le"] = "pcm_s16le"

    @field_validator("sample_rate_hz", "channels", mode="before")
    @classmethod
    def require_integer(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("sample rate and channel count must be integers")
        return value


class AudioChunk(ContractModel):
    """One validated chunk; start_ms is relative to the audio stream start."""

    session_id: str = Field(min_length=1, pattern=r"\S")
    sequence_id: int = Field(strict=True, ge=0)
    start_ms: int = Field(strict=True, ge=0)
    duration_ms: int = Field(strict=True, gt=0)
    format: AudioFormat
    pcm: bytes = Field(strict=True, min_length=1, repr=False)

    @model_validator(mode="after")
    def require_matching_pcm_length(self) -> Self:
        # 16 samples/ms × 2 bytes/sample × one channel = 32 bytes/ms.
        expected = self.duration_ms * 32
        if len(self.pcm) != expected:
            raise ValueError(f"expected {expected} PCM bytes, received {len(self.pcm)}")
        return self


class AudioError(ErrorEnvelope):
    """Safe audio error data returned by a later CLI or API boundary."""

    code: str = Field(pattern=r"^AUDIO_.+")


SpeechEventKind = Literal["wake", "speech_start", "speech_end"]


class SpeechEvent(ContractModel):
    """Normalized audio event (W1 produces; W2 and W5 consume). Never carries PCM.

    ``sequence_id`` orders speech events within one session; ``at_ms`` is relative
    to the audio stream start. ``wake_word`` and ``score`` are set only for ``wake``.
    """

    kind: SpeechEventKind
    session_id: str = Field(min_length=1, pattern=r"\S")
    correlation_id: str = Field(min_length=1, pattern=r"\S")
    sequence_id: int = Field(strict=True, ge=0)
    at_ms: int = Field(strict=True, ge=0)
    wake_word: str | None = Field(default=None, min_length=1, pattern=r"\S")
    score: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def wake_fields_only_on_wake(self) -> Self:
        is_wake = self.kind == "wake"
        has_wake_fields = self.wake_word is not None and self.score is not None
        if is_wake and not has_wake_fields:
            raise ValueError("wake events need wake_word and score")
        if not is_wake and (self.wake_word is not None or self.score is not None):
            raise ValueError("wake_word and score are only allowed on wake events")
        return self


CaptureState = Literal["idle", "listening", "capturing", "paused", "stopped"]


class CaptureStatus(ContractModel):
    """What the microphone is doing, for the UI's capture indicator (W1 → W5 → W6).

    ``idle``: not started. ``listening``: waiting for the wake word.
    ``capturing``: recording an utterance after the wake word (or with the wake
    word off). ``paused`` / ``stopped``: capture is off. Audio is never written
    to disk in any state.
    """

    session_id: str = Field(min_length=1, pattern=r"\S")
    state: CaptureState
    source: Literal["mock", "mic"]
    wake_required: bool
    wake_word: str | None = Field(default=None, min_length=1, pattern=r"\S")
