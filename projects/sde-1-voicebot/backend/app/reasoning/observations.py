"""Timestamped, source-linked screen observations with consent and freshness rules.

Every observation keeps the ``ContextItem`` (text plus ``SourceReference``) and
the time its frame was captured. Frames are dropped when they are stale (older
than ``max_age_ms`` or dated in the future), when their frame ID was already
seen, or when their text is identical to the last accepted frame (the screen
did not change). Withdrawing consent disables capture and clears everything
that has not been used yet.
"""

import hashlib
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from app.contracts.reasoning import ContextItem, ScreenContext
from app.reasoning.capture import CaptureAdapter
from app.reasoning.vision import VisionAdapter

FrameStatus = Literal["accepted", "stale", "duplicate", "no_consent", "empty"]


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{name} must be timezone-aware UTC")


@dataclass(frozen=True)
class Observation:
    """One piece of screen text, where it came from, and when it was seen."""

    item: ContextItem
    frame_id: str
    observed_at: datetime


@dataclass(frozen=True)
class FrameDecision:
    status: FrameStatus
    frame_id: str
    added: int = 0


def frame_content_hash(context: ScreenContext) -> str:
    """Hash of the frame's visible text only; IDs and times are ignored."""
    texts = sorted(item.text for item in context.items)
    return hashlib.sha256("\x1f".join(texts).encode("utf-8")).hexdigest()


class ObservationStore:
    """Pending observations for the next reasoning request (in memory only)."""

    def __init__(
        self,
        *,
        max_age_ms: int = 30_000,
        max_observations: int = 50,
        max_seen_frames: int = 500,
    ) -> None:
        for value, name in (
            (max_age_ms, "max_age_ms"),
            (max_observations, "max_observations"),
            (max_seen_frames, "max_seen_frames"),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.max_age = timedelta(milliseconds=max_age_ms)
        self._max_observations = max_observations
        self._pending: deque[Observation] = deque()
        self._seen_frames: deque[str] = deque(maxlen=max_seen_frames)
        self._last_hash: str | None = None
        self._consent = False

    @property
    def consent_given(self) -> bool:
        return self._consent

    def give_consent(self) -> None:
        self._consent = True

    def withdraw_consent(self, capture: CaptureAdapter | None = None) -> None:
        """Stop capture and forget every observation that was not used yet."""
        self._consent = False
        self._pending.clear()
        self._last_hash = None
        disable = getattr(capture, "disable", None)
        if callable(disable):
            disable()

    def _is_stale(self, captured_at: datetime, now: datetime) -> bool:
        return captured_at > now or now - captured_at > self.max_age

    def add_frame(self, context: ScreenContext, *, now: datetime) -> FrameDecision:
        """Accept a frame's items as observations, or say why it was dropped."""
        if not isinstance(context, ScreenContext):
            raise TypeError("context must be a ScreenContext")
        _require_utc(now, "now")
        frame_id = context.frame_id
        if not self._consent:
            return FrameDecision("no_consent", frame_id)
        if self._is_stale(context.captured_at, now):
            return FrameDecision("stale", frame_id)
        content_hash = frame_content_hash(context)
        if frame_id in self._seen_frames or content_hash == self._last_hash:
            return FrameDecision("duplicate", frame_id)
        self._seen_frames.append(frame_id)
        if not context.items:
            return FrameDecision("empty", frame_id)
        self._last_hash = content_hash
        for item in context.items:
            self._pending.append(Observation(item, frame_id, context.captured_at))
        while len(self._pending) > self._max_observations:
            self._pending.popleft()
        return FrameDecision("accepted", frame_id, added=len(context.items))

    def observe(
        self, capture: CaptureAdapter, vision: VisionAdapter, *, now: datetime
    ) -> FrameDecision | None:
        """Capture one frame (only if consent and capture are on) and add it."""
        if not self._consent:
            return None
        outcome = capture.capture(now)
        if outcome.status != "captured" or outcome.frame is None:
            return None
        context = vision.extract(outcome.frame, capture_enabled=True)
        return self.add_frame(context, now=now)

    def pending(self, *, now: datetime) -> list[Observation]:
        """Fresh pending observations, oldest first; stale ones are dropped."""
        _require_utc(now, "now")
        fresh = [o for o in self._pending if not self._is_stale(o.observed_at, now)]
        self._pending = deque(fresh)
        return list(fresh)

    def latest_frame(self, *, now: datetime) -> list[Observation]:
        """Observations from the most recent fresh frame only."""
        fresh = self.pending(now=now)
        if not fresh:
            return []
        newest = fresh[-1].frame_id
        return [o for o in fresh if o.frame_id == newest]
