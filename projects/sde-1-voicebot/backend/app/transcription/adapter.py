"""Provider-neutral transcription adapter protocol."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

try:
    from app.contracts.audio import AudioChunk
except ImportError:
    from typing import Any

    AudioChunk = Any  # type: ignore

from app.contracts.transcription import TranscriptEvent


@runtime_checkable
class TranscriptionAdapter(Protocol):
    """Clean provider-neutral interface for transcription services."""

    def transcribe(
        self,
        chunks: Sequence[AudioChunk],
        *,
        session_id: str,
        correlation_id: str,
        timestamp: datetime,
    ) -> list[TranscriptEvent]:
        """Transcribe ordered audio chunks into timestamped transcript events."""
        ...

    def health(self) -> str:
        """Return provider health status (e.g. 'ready')."""
        ...

    def cancel(self, session_id: str) -> None:
        """Cancel transcription for a session, preventing subsequent output."""
        ...
