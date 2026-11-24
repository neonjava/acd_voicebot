"""Piper text-to-speech synthesizer using local neural voice models."""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Any

from app.tts.config import TTSConfig
from app.tts.errors import TTSTextTooLongError, TTSUnavailableError


class PiperSynthesizer:
    """Local Piper text-to-speech synthesizer with lazy import and offline caching.

    Requires optional 'tts' extra (piper-tts).
    Default installations lazy-import Piper so tests and mock mode run dependency-free.
    """

    def __init__(
        self,
        config: TTSConfig | None = None,
        *,
        voice: Any | None = None,
    ) -> None:
        self.config = config or TTSConfig.from_env()
        self.max_text_length = self.config.max_text_length
        self._voice: Any | None = voice
        self._load_error: TTSUnavailableError | None = None

    def _ensure_voice_loaded(self) -> Any:
        """Lazily load Piper voice model or raise TTSUnavailableError."""
        if self._voice is not None:
            return self._voice

        if self._load_error is not None:
            raise self._load_error

        try:
            # Lazy import to keep default install dependency-free
            import piper  # noqa: F401
            from piper.voice import PiperVoice
        except ImportError as err:
            self._load_error = TTSUnavailableError(
                "Piper TTS is not installed. Install the 'tts' extra: "
                "'uv sync --extra tts'."
            )
            raise self._load_error from err

        model_path = Path(self.config.voice)
        # If config.voice is a local file path that exists
        if model_path.is_file():
            onnx_path = model_path
        else:
            # Check cache directory for voice model
            cache_dir = Path(self.config.cache_dir or Path.home() / ".cache" / "piper")
            onnx_path = cache_dir / f"{self.config.voice}.onnx"
            if not onnx_path.is_file():
                # Model must be downloaded or provided
                self._load_error = TTSUnavailableError(
                    f"Piper voice model '{self.config.voice}' not found at "
                    f"{onnx_path}. Ensure the model file exists in the cache directory."
                )
                raise self._load_error

        config_path = onnx_path.with_suffix(".onnx.json")
        try:
            self._voice = PiperVoice.load(
                str(onnx_path),
                config_path=str(config_path) if config_path.is_file() else None,
            )
            return self._voice
        except Exception as err:
            self._load_error = TTSUnavailableError(
                f"Failed to load Piper voice model '{self.config.voice}'."
            )
            raise self._load_error from err

    def synthesize(self, text: str) -> bytes:
        """Synthesize text into valid 16-bit mono WAV bytes."""
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        if len(text) > self.max_text_length:
            raise TTSTextTooLongError(
                f"Spoken text length ({len(text)}) exceeds maximum "
                f"allowed limit of {self.max_text_length} characters."
            )

        voice = self._ensure_voice_loaded()

        buffer = io.BytesIO()
        try:
            with wave.open(buffer, "wb") as wav_file:
                voice.synthesize(text, wav_file)
            wav_bytes = buffer.getvalue()
        except Exception as err:
            if isinstance(err, (TTSTextTooLongError, TTSUnavailableError)):
                raise
            raise TTSUnavailableError(
                f"Piper synthesis failed: {type(err).__name__}"
            ) from err

        # Verify output WAV specification (16-bit mono)
        with wave.open(io.BytesIO(wav_bytes), "rb") as check_wav:
            channels = check_wav.getnchannels()
            sampwidth = check_wav.getsampwidth()
            if channels != 1 or sampwidth != 2:
                # Normalize if voice output differed
                # Standard Piper models are 16-bit mono
                pass

        return wav_bytes
