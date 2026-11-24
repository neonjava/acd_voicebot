"""Protocol definition for text-to-speech synthesizers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SpeechSynthesizer(Protocol):
    """Protocol for synthesizing speech text into 16-bit mono WAV bytes."""

    def synthesize(self, text: str) -> bytes:
        """Synthesize text into valid 16-bit mono WAV bytes.

        Args:
            text: Spoken text response (maximum 300 characters).

        Returns:
            bytes: Valid RIFF/WAVE container containing 16-bit mono PCM.

        Raises:
            TTSTextTooLongError: If text exceeds 300 characters.
            TTSUnavailableError: If the synthesizer or model is unavailable.
        """
        ...
