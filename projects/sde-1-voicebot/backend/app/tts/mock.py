"""Deterministic mock speech synthesizer for testing and offline operation."""

from __future__ import annotations

import io
import math
import struct
import wave

from app.tts.config import TTSConfig
from app.tts.errors import TTSTextTooLongError


class MockSynthesizer:
    """Deterministic in-memory speech synthesizer returning valid 16-bit mono WAV."""

    def __init__(self, config: TTSConfig | None = None) -> None:
        self.config = config or TTSConfig()
        self.sample_rate = self.config.sample_rate
        self.max_text_length = self.config.max_text_length

    def synthesize(self, text: str) -> bytes:
        """Synthesize text into a valid 16-bit mono WAV container.

        Generates deterministic PCM audio using standard library wave module.
        Requires zero dependencies, zero GPU, and zero disk/network access.
        """
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        if len(text) > self.max_text_length:
            raise TTSTextTooLongError(
                f"Spoken text length ({len(text)}) exceeds maximum "
                f"allowed limit of {self.max_text_length} characters."
            )

        # Base duration of 200ms plus 15ms per character (capped at 4 seconds)
        stripped = text.strip()
        duration_ms = 200 + min(len(stripped) * 15, 3800)
        num_samples = int((duration_ms / 1000.0) * self.sample_rate)

        # Generate a mild synthetic tone (440 Hz) with soft envelope
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit signed integer (2 bytes)
            wav_file.setframerate(self.sample_rate)

            samples = bytearray()
            freq = 440.0
            for i in range(num_samples):
                # Apply gentle linear attack and decay to avoid pop/clicks
                envelope = 1.0
                if i < 160:
                    envelope = i / 160.0
                elif i > num_samples - 160:
                    envelope = max(0.0, (num_samples - i) / 160.0)

                phase = 2.0 * math.pi * freq * (i / self.sample_rate)
                val = int(envelope * 8000.0 * math.sin(phase))
                samples.extend(struct.pack("<h", max(-32768, min(32767, val))))

            wav_file.writeframes(samples)

        return buffer.getvalue()
