"""Text-to-speech package for Academiaai AI Voicebot."""

from __future__ import annotations

from app.tts.config import TTSConfig, TTSProvider
from app.tts.errors import TTSError, TTSTextTooLongError, TTSUnavailableError
from app.tts.mock import MockSynthesizer
from app.tts.piper import PiperSynthesizer
from app.tts.protocol import SpeechSynthesizer


def get_synthesizer(config: TTSConfig | None = None) -> SpeechSynthesizer:
    """Create a speech synthesizer based on configuration."""
    cfg = config or TTSConfig.from_env()
    if cfg.provider == "piper":
        return PiperSynthesizer(cfg)
    return MockSynthesizer(cfg)


__all__ = [
    "MockSynthesizer",
    "PiperSynthesizer",
    "SpeechSynthesizer",
    "TTSConfig",
    "TTSError",
    "TTSProvider",
    "TTSTextTooLongError",
    "TTSUnavailableError",
    "get_synthesizer",
]
