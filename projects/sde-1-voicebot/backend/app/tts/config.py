"""Configuration for text-to-speech providers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TTSProvider = Literal["mock", "piper"]


@dataclass(frozen=True)
class TTSConfig:
    """Settings for text-to-speech synthesizer."""

    provider: TTSProvider = "mock"
    voice: str = "en_US-lessac-medium"
    sample_rate: int = 16000
    cache_dir: str | None = None
    max_text_length: int = 300

    def __post_init__(self) -> None:
        if self.provider not in ("mock", "piper"):
            raise ValueError(f"Unknown TTS provider '{self.provider}'")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be a positive integer")
        if self.max_text_length <= 0:
            raise ValueError("max_text_length must be a positive integer")

    @classmethod
    def from_env(cls) -> TTSConfig:
        """Resolve TTS configuration from environment variables."""
        raw_provider = os.getenv("TTS_PROVIDER", "mock").strip().lower()
        provider: TTSProvider = "piper" if raw_provider == "piper" else "mock"
        voice = os.getenv("TTS_VOICE", "en_US-lessac-medium").strip()

        raw_sr = os.getenv("TTS_SAMPLE_RATE")
        sample_rate = int(raw_sr) if raw_sr and raw_sr.isdigit() else 16000

        cache_dir = os.getenv("TTS_CACHE_DIR")
        if not cache_dir:
            cache_dir = str(Path.home() / ".cache" / "piper")

        return cls(
            provider=provider,
            voice=voice,
            sample_rate=sample_rate,
            cache_dir=cache_dir,
        )
