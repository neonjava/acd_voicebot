"""Mock-only audio device adapter and explicit permission handling."""

from enum import Enum
from typing import Protocol

from app.audio.chunker import chunk_pcm
from app.audio.source import make_fake_pcm
from app.contracts.audio import AudioChunk


class PermissionState(str, Enum):
    prompt = "prompt"
    granted = "granted"
    denied = "denied"
    unavailable = "unavailable"


class AudioDeviceError(ValueError):
    """Safe device failure with a stable code for a later API boundary."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class AudioDevice(Protocol):
    @property
    def permission(self) -> PermissionState: ...

    def list_devices(self) -> tuple[str, ...]: ...

    def request_permission(self, device_id: str) -> PermissionState: ...

    def select_device(self, device_id: str) -> None: ...

    def read_chunks(
        self, *, session_id: str, duration_ms: int, chunk_ms: int = 20
    ) -> list[AudioChunk]: ...


class MockAudioDevice:
    """Generate deterministic PCM in memory; never opens an operating-system device."""

    DEVICE_ID = "mock:microphone"

    def __init__(
        self, *, allow_permission: bool = True, available: bool = True
    ) -> None:
        if type(allow_permission) is not bool or type(available) is not bool:
            raise ValueError("device settings must be booleans")
        self._allow_permission = allow_permission
        self._available = available
        self._permission = (
            PermissionState.prompt if available else PermissionState.unavailable
        )
        self._selected: str | None = None

    @property
    def permission(self) -> PermissionState:
        return self._permission

    def list_devices(self) -> tuple[str, ...]:
        return (self.DEVICE_ID,) if self._available else ()

    def request_permission(self, device_id: str) -> PermissionState:
        if device_id not in self.list_devices():
            self._permission = PermissionState.unavailable
            raise AudioDeviceError(
                "AUDIO_DEVICE_UNAVAILABLE", "Audio device is unavailable."
            )
        self._permission = (
            PermissionState.granted
            if self._allow_permission
            else PermissionState.denied
        )
        return self._permission

    def select_device(self, device_id: str) -> None:
        if device_id not in self.list_devices():
            raise AudioDeviceError(
                "AUDIO_DEVICE_UNAVAILABLE", "Audio device is unavailable."
            )
        if self._permission is not PermissionState.granted:
            raise AudioDeviceError(
                "AUDIO_PERMISSION_DENIED", "Audio permission is not granted."
            )
        self._selected = device_id

    def read_chunks(
        self, *, session_id: str, duration_ms: int, chunk_ms: int = 20
    ) -> list[AudioChunk]:
        if self._selected is None or self._permission is not PermissionState.granted:
            raise AudioDeviceError(
                "AUDIO_DEVICE_NOT_READY", "Audio device is not ready."
            )
        return chunk_pcm(
            make_fake_pcm(duration_ms=duration_ms),
            session_id=session_id,
            chunk_ms=chunk_ms,
        )
