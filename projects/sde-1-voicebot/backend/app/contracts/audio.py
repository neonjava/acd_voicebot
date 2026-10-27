"""Audio contracts shared by the mock source and transcription workstreams."""

from typing import Literal, Self

from app.contracts.common import ContractModel, ErrorEnvelope
from pydantic import Field, field_validator, model_validator


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
