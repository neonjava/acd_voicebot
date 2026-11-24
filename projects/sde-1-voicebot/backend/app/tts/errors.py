"""Safe, typed errors for speech synthesis."""

from __future__ import annotations


class TTSError(Exception):
    """Base exception for text-to-speech operations."""

    def __init__(self, message: str, *, error_code: str = "TTS_ERROR") -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class TTSUnavailableError(TTSError):
    """Raised when text-to-speech provider or voice model is unavailable."""

    def __init__(
        self,
        message: str = "Text-to-speech provider or voice model is unavailable.",
    ) -> None:
        super().__init__(message, error_code="TTS_UNAVAILABLE")


class TTSTextTooLongError(TTSError, ValueError):
    """Raised when text exceeds the maximum permitted length for spoken replies."""

    def __init__(
        self,
        message: str = (
            "Spoken reply text exceeds maximum allowed limit of 300 characters."
        ),
    ) -> None:
        super().__init__(message, error_code="TTS_TEXT_TOO_LONG")
