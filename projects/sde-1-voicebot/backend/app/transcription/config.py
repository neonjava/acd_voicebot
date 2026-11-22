"""Transcription configuration for local faster-whisper and mock fallback."""

import os
from dataclasses import dataclass
from typing import Literal

STTProviderType = Literal["mock", "faster_whisper"]


@dataclass(frozen=True)
class TranscriptionConfig:
    """Configuration for speech-to-text transcription."""

    provider: STTProviderType = "mock"
    model_size: str = "base"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "en"
    confidence_threshold: float = 0.4
    fallback_to_mock: bool = True

    @classmethod
    def from_env(cls) -> "TranscriptionConfig":
        """Load configuration from environment variables with safe defaults."""
        raw_provider = os.getenv("STT_PROVIDER", "mock").lower()
        provider: STTProviderType = (
            "faster_whisper" if raw_provider == "faster_whisper" else "mock"
        )
        model_size = os.getenv("STT_MODEL_SIZE", "base")
        device = os.getenv("STT_DEVICE", "cpu")
        compute_type = os.getenv("STT_COMPUTE_TYPE", "int8")
        language = os.getenv("STT_LANGUAGE", "en")

        try:
            conf_thresh = float(os.getenv("STT_CONFIDENCE_THRESHOLD", "0.4"))
        except ValueError:
            conf_thresh = 0.4

        raw_fallback = os.getenv("STT_FALLBACK_TO_MOCK", "true").lower()
        fallback = raw_fallback in ("1", "true", "yes", "on")

        return cls(
            provider=provider,
            model_size=model_size,
            device=device,
            compute_type=compute_type,
            language=language,
            confidence_threshold=conf_thresh,
            fallback_to_mock=fallback,
        )
