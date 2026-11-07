"""Opt-in screen capture adapter boundary with a synthetic, off-by-default mock.

No code in this module reads the real screen. ``SyntheticCaptureAdapter`` only
returns frames it was given, and only after ``enable()`` is called. A future
real adapter must implement ``CaptureAdapter`` and keep the same defaults.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Literal, Protocol

from app.contracts.common import ErrorEnvelope
from app.contracts.reasoning import CaptureSettings

CaptureStatus = Literal["captured", "disabled", "throttled", "rejected", "exhausted"]


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{name} must be timezone-aware UTC")


@dataclass(frozen=True)
class SyntheticFrame:
    """A made-up frame for tests and demos. Never a real screenshot.

    ``image_bytes`` is a placeholder payload used only for size limits.
    ``text_regions`` are (region_id, text) pairs that the mock OCR reads.
    """

    frame_id: str
    width: int
    height: int
    image_bytes: bytes
    text_regions: tuple[tuple[str, str], ...]
    captured_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.frame_id.strip():
            raise ValueError("frame_id must be nonblank")
        for value, name in ((self.width, "width"), (self.height, "height")):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.image_bytes) is not bytes:
            raise ValueError("image_bytes must be bytes")
        if self.captured_at is not None:
            _require_utc(self.captured_at, "captured_at")


@dataclass(frozen=True)
class CaptureOutcome:
    status: CaptureStatus
    frame: SyntheticFrame | None = None
    error: ErrorEnvelope | None = None


class CaptureAdapter(Protocol):
    @property
    def settings(self) -> CaptureSettings: ...

    def capture(self, now: datetime) -> CaptureOutcome: ...


class SyntheticCaptureAdapter:
    """Return supplied synthetic frames under the opt-in, sampling and size rules."""

    def __init__(
        self,
        frames: Sequence[SyntheticFrame],
        *,
        settings: CaptureSettings | None = None,
        correlation_id: str = "capture-mock",
    ) -> None:
        if not isinstance(correlation_id, str) or not correlation_id.strip():
            raise ValueError("correlation_id must be a nonblank string")
        self._frames = list(frames)
        self._settings = settings if settings is not None else CaptureSettings()
        self._correlation_id = correlation_id
        self._next = 0
        self._last_sample_at: datetime | None = None

    @property
    def settings(self) -> CaptureSettings:
        return self._settings

    def enable(self) -> None:
        """Explicit user opt-in."""
        self._settings = self._settings.model_copy(update={"enabled": True})

    def disable(self) -> None:
        self._settings = self._settings.model_copy(update={"enabled": False})
        self._last_sample_at = None

    def capture(self, now: datetime) -> CaptureOutcome:
        _require_utc(now, "now")
        settings = self._settings
        if not settings.enabled:
            return CaptureOutcome(status="disabled")

        interval = timedelta(milliseconds=settings.sampling_interval_ms)
        if self._last_sample_at is not None and now - self._last_sample_at < interval:
            return CaptureOutcome(status="throttled")

        if self._next >= len(self._frames):
            return CaptureOutcome(status="exhausted")

        frame = self._frames[self._next]
        self._next += 1
        self._last_sample_at = now

        too_large = (
            len(frame.image_bytes) > settings.max_frame_bytes
            or frame.width > settings.max_width
            or frame.height > settings.max_height
        )
        if too_large:
            return CaptureOutcome(
                status="rejected",
                error=ErrorEnvelope(
                    code="CAPTURE_FRAME_TOO_LARGE",
                    message_safe_for_user="The screen frame exceeds the size limits.",
                    retryable=False,
                    correlation_id=self._correlation_id,
                    details_redacted={"frame_id": frame.frame_id},
                ),
            )
        return CaptureOutcome(status="captured", frame=replace(frame, captured_at=now))
