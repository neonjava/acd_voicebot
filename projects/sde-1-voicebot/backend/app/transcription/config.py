"""Transcription configuration for local faster-whisper and mock fallback."""

import os
from dataclasses import dataclass
from typing import Literal

STTProviderType = Literal["mock", "faster_whisper"]


def detect_default_device() -> str:
    """Detect CUDA when available, otherwise fall back to CPU."""
    try:
        import torch

        if hasattr(torch, "cuda") and torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


@dataclass(frozen=True)
class TranscriptionConfig:
    """Configuration for speech-to-text transcription."""

    provider: STTProviderType = "mock"
    model_size: str = "base"
    device: str = "auto"
    compute_type: str = "auto"
    language: str = "en"
    confidence_threshold: float = 0.4
    fallback_to_mock: bool = True

    def __post_init__(self) -> None:
        if type(self.confidence_threshold) not in (int, float) or not (
            0.0 <= self.confidence_threshold <= 1.0
        ):
            raise ValueError("confidence_threshold must be a float between 0.0 and 1.0")

    def resolve_device_and_compute(self) -> tuple[str, str]:
        """Resolve device and compute_type respecting CUDA availability."""
        resolved_device = (
            detect_default_device() if self.device == "auto" else self.device
        )
        if self.compute_type == "auto":
            resolved_compute = "float16" if resolved_device == "cuda" else "int8"
        else:
            resolved_compute = self.compute_type

        # CPU does not support float16 execution in faster-whisper
        if resolved_device == "cpu" and resolved_compute == "float16":
            resolved_compute = "int8"

        return resolved_device, resolved_compute

    @classmethod
    def from_env(cls) -> "TranscriptionConfig":
        """Load configuration from environment variables with safe defaults."""
        raw_provider = os.getenv("STT_PROVIDER", "mock").lower()
        provider: STTProviderType = (
            "faster_whisper" if raw_provider == "faster_whisper" else "mock"
        )
        model_size = os.getenv("STT_MODEL_SIZE", "base")
        device = os.getenv("STT_DEVICE", "auto")
        compute_type = os.getenv("STT_COMPUTE_TYPE", "auto")
        language = os.getenv("STT_LANGUAGE", "en")

        try:
            conf_thresh = float(os.getenv("STT_CONFIDENCE_THRESHOLD", "0.4"))
            if not (0.0 <= conf_thresh <= 1.0):
                conf_thresh = 0.4
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
