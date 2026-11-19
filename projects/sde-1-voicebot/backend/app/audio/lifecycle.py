"""Audio-capture lifecycle; independent of W5's backend session lifecycle."""

import time
from collections.abc import Callable
from enum import Enum
from typing import TYPE_CHECKING

from app.audio.buffer import BoundedAudioBuffer
from app.audio.device import AudioDevice, AudioDeviceError, PermissionState
from app.contracts.audio import AudioChunk, AudioError

if TYPE_CHECKING:
    from app.audio.config import AudioConfig


class CaptureState(str, Enum):
    created = "created"
    active = "active"
    paused = "paused"
    stopped = "stopped"


class AudioCaptureController:
    """Manage capture state, monotonic chunk sequencing, recovery, and cancellation."""

    def __init__(
        self,
        *,
        session_id: str,
        device: AudioDevice,
        buffer: BoundedAudioBuffer,
        correlation_id: str = "correlation-demo",
        max_reconnect_attempts: int = 3,
        reconnect_backoff_ms: int = 50,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a nonempty string")
        if not isinstance(correlation_id, str) or not correlation_id.strip():
            raise ValueError("correlation_id must be a nonempty string")
        if type(max_reconnect_attempts) is not int or max_reconnect_attempts < 0:
            raise ValueError("max_reconnect_attempts must be a nonnegative integer")
        if type(reconnect_backoff_ms) is not int or reconnect_backoff_ms < 0:
            raise ValueError("reconnect_backoff_ms must be a nonnegative integer")
        self.session_id = session_id
        self.correlation_id = correlation_id
        self.device = device
        self.buffer = buffer
        self.state = CaptureState.created
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_backoff_ms = reconnect_backoff_ms
        self._sleep = sleep_fn if sleep_fn is not None else time.sleep
        self._next_sequence = 0
        self._next_start_ms = 0
        self._device_id: str | None = None
        self.cancelled = False
        self.reconnect_count = 0
        self.overruns = 0
        self.reconnect_backoffs_ms: list[int] = []
        self.last_error: AudioError | None = None

    @classmethod
    def from_config(
        cls,
        config: "AudioConfig",
        *,
        session_id: str,
        correlation_id: str,
        device: AudioDevice,
        buffer: BoundedAudioBuffer,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> "AudioCaptureController":
        """Build a controller that uses the configured reconnect policy."""
        return cls(
            session_id=session_id,
            correlation_id=correlation_id,
            device=device,
            buffer=buffer,
            max_reconnect_attempts=config.reconnect_max_attempts,
            reconnect_backoff_ms=config.reconnect_backoff_ms,
            sleep_fn=sleep_fn,
        )

    def start(self, device_id: str) -> None:
        if self.state is not CaptureState.created:
            raise ValueError("capture can only start from created")
        permission = self.device.request_permission(device_id)
        if permission is not PermissionState.granted:
            raise AudioDeviceError(
                "AUDIO_PERMISSION_DENIED", "Audio permission was denied."
            )
        self.device.select_device(device_id)
        self._device_id = device_id
        self.state = CaptureState.active

    def pause(self) -> None:
        if self.state is not CaptureState.active:
            raise ValueError("capture can only pause while active")
        self.state = CaptureState.paused

    def resume(self) -> None:
        if self.state is not CaptureState.paused:
            raise ValueError("capture can only resume while paused")
        self.state = CaptureState.active

    def _mark_gap(self, duration_ms: int) -> None:
        """Skip one sequence ID and one chunk of time before the next chunk.

        Used when input audio was lost (mic overrun or device loss), so the
        pipeline sees a gap and never merges speech across missing audio.
        """
        self._next_sequence += 1
        self._next_start_ms += duration_ms

    def _close_device(self) -> None:
        close_fn = getattr(self.device, "close", None)
        if callable(close_fn):
            close_fn()

    def stop(self) -> None:
        if self.state is CaptureState.stopped:
            raise ValueError("capture is already stopped")
        self.buffer.release()
        self._close_device()
        self.state = CaptureState.stopped

    def cancel(self) -> None:
        """Cancel capture immediately, stop reading, and release buffered audio."""
        self.cancelled = True
        self.buffer.release()
        self._close_device()
        self.state = CaptureState.stopped

    def _reconnect_and_read(
        self, *, duration_ms: int, chunk_ms: int
    ) -> list[AudioChunk]:
        assert self._device_id is not None
        for attempt in range(self.max_reconnect_attempts):
            if self.cancelled or self.state is CaptureState.stopped:
                self.buffer.release()
                raise AudioDeviceError(
                    "AUDIO_CAPTURE_CANCELLED", "Audio capture was cancelled."
                )
            backoff_ms = self.reconnect_backoff_ms * (2**attempt)
            self.reconnect_backoffs_ms.append(backoff_ms)
            if backoff_ms > 0:
                self._sleep(backoff_ms / 1000.0)
            if self.cancelled or self.state is CaptureState.stopped:
                self.buffer.release()
                raise AudioDeviceError(
                    "AUDIO_CAPTURE_CANCELLED", "Audio capture was cancelled."
                )
            try:
                if self._device_id not in self.device.list_devices():
                    raise AudioDeviceError(
                        "AUDIO_DEVICE_LOST", "Audio device is unavailable."
                    )
                if self.device.permission is not PermissionState.granted:
                    permission = self.device.request_permission(self._device_id)
                    if permission is not PermissionState.granted:
                        raise AudioDeviceError(
                            "AUDIO_PERMISSION_DENIED", "Audio permission was denied."
                        )
                self.device.select_device(self._device_id)
                chunks = self.device.read_chunks(
                    session_id=self.session_id,
                    duration_ms=duration_ms,
                    chunk_ms=chunk_ms,
                )
            except AudioDeviceError as exc:
                if exc.code == "AUDIO_PERMISSION_DENIED":
                    raise
                continue
            self.reconnect_count += 1
            return chunks

        error = AudioError(
            code="AUDIO_DEVICE_LOST",
            message_safe_for_user="Audio device was lost and could not be reconnected.",
            retryable=False,
            correlation_id=self.correlation_id,
            details_redacted={"attempts": str(self.max_reconnect_attempts)},
        )
        self.last_error = error
        self._close_device()
        raise AudioDeviceError(
            "AUDIO_DEVICE_LOST",
            error.message_safe_for_user,
            audio_error=error,
        )

    def produce(self, *, duration_ms: int, chunk_ms: int = 20) -> int:
        """Capture chunks, recovering from transient device loss without reusing IDs."""
        if self.state is not CaptureState.active or self.cancelled:
            raise ValueError("capture must be active to produce audio")
        try:
            chunks = self.device.read_chunks(
                session_id=self.session_id, duration_ms=duration_ms, chunk_ms=chunk_ms
            )
        except AudioDeviceError as exc:
            if (
                exc.code not in {"AUDIO_DEVICE_LOST", "AUDIO_DEVICE_UNAVAILABLE"}
                or self._device_id is None
            ):
                raise
            chunks = self._reconnect_and_read(
                duration_ms=duration_ms, chunk_ms=chunk_ms
            )
            if chunks:
                # Audio was lost while the device was gone.
                self._mark_gap(chunks[0].duration_ms)

        consume_overrun = getattr(self.device, "consume_overrun", None)
        if callable(consume_overrun) and consume_overrun() and chunks:
            self.overruns += 1
            self._mark_gap(chunks[0].duration_ms)

        retained = 0
        for chunk in chunks:
            if self.cancelled or self.state is not CaptureState.active:
                self.buffer.release()
                break
            absolute = AudioChunk(
                session_id=chunk.session_id,
                sequence_id=self._next_sequence,
                start_ms=self._next_start_ms,
                duration_ms=chunk.duration_ms,
                format=chunk.format,
                pcm=chunk.pcm,
            )
            retained += self.buffer.push(absolute)
            self._next_sequence += 1
            self._next_start_ms += chunk.duration_ms
        return retained
