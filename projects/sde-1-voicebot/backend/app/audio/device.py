"""Audio device adapters, permission handling, and optional real mic capture."""

from enum import Enum
from typing import Protocol

from app.audio.chunker import chunk_pcm
from app.audio.source import make_fake_pcm
from app.contracts.audio import AudioChunk, AudioFormat


class PermissionState(str, Enum):
    prompt = "prompt"
    granted = "granted"
    denied = "denied"
    unavailable = "unavailable"


class AudioDeviceError(ValueError):
    """Safe device failure with a stable code for a later API boundary."""

    def __init__(
        self, code: str, message: str, *, audio_error: object | None = None
    ) -> None:
        self.code = code
        self.audio_error = audio_error
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
        self._recover_after_probes: int | None = None

    @property
    def permission(self) -> PermissionState:
        return self._permission

    def disconnect(self, *, failures_before_recover: int | None = None) -> None:
        """Simulate mid-session device loss, with optional deterministic recovery."""
        if failures_before_recover is not None and (
            type(failures_before_recover) is not int or failures_before_recover < 0
        ):
            raise ValueError("failures_before_recover must be a nonnegative integer")
        self._available = False
        self._selected = None
        self._recover_after_probes = failures_before_recover

    def reconnect(self) -> None:
        """Restore simulated availability so a subsequent select/read can succeed."""
        self._available = True
        self._recover_after_probes = None

    def close(self) -> None:
        """Release any selected mock device handle."""
        self._selected = None

    def list_devices(self) -> tuple[str, ...]:
        if not self._available and self._recover_after_probes is not None:
            if self._recover_after_probes == 0:
                self._available = True
                self._recover_after_probes = None
            else:
                self._recover_after_probes -= 1
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
        if not self._available:
            raise AudioDeviceError(
                "AUDIO_DEVICE_LOST", "Audio device was lost mid-session."
            )
        if self._selected is None or self._permission is not PermissionState.granted:
            raise AudioDeviceError(
                "AUDIO_DEVICE_NOT_READY", "Audio device is not ready."
            )
        return chunk_pcm(
            make_fake_pcm(duration_ms=duration_ms),
            session_id=session_id,
            chunk_ms=chunk_ms,
        )


def _load_sounddevice() -> object:
    """Import sounddevice lazily so default installs work without the audio extra."""
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise AudioDeviceError(
            "AUDIO_DEPENDENCY_MISSING",
            "Real microphone capture requires the audio extra.",
        ) from exc
    return sd


class SoundDeviceMicrophone:
    """Real 16 kHz mono pcm_s16le microphone adapter backed by sounddevice."""

    DEVICE_ID = "mic:default"

    def __init__(
        self,
        *,
        sample_rate_hz: int = 16000,
        channels: int = 1,
        encoding: str = "pcm_s16le",
        device: str | int | None = None,
    ) -> None:
        self.format = AudioFormat(
            sample_rate_hz=sample_rate_hz,
            channels=channels,
            encoding=encoding,
        )
        self._configured_device = device
        self._permission = PermissionState.prompt
        self._selected: str | None = None
        self._stream: object | None = None

    @property
    def permission(self) -> PermissionState:
        return self._permission

    def _resolve_device_arg(self, device_id: str) -> str | int | None:
        if device_id == self.DEVICE_ID:
            return self._configured_device
        prefix = "mic:"
        if device_id.startswith(prefix):
            rest = device_id[len(prefix) :]
            idx_str, _, _ = rest.partition(":")
            if idx_str.isdigit():
                return int(idx_str)
        return device_id

    def list_devices(self) -> tuple[str, ...]:
        sd = _load_sounddevice()
        try:
            devices = sd.query_devices()  # type: ignore[attr-defined]
        except Exception:
            return ()
        result: list[str] = []
        has_input = False
        for idx, info in enumerate(devices):
            max_in = int(info.get("max_input_channels", 0))
            if max_in > 0:
                has_input = True
                name = str(info.get("name", "input")).strip() or "input"
                result.append(f"mic:{idx}:{name}")
        if not has_input:
            return ()
        return (self.DEVICE_ID, *result)

    def request_permission(self, device_id: str) -> PermissionState:
        if device_id not in self.list_devices():
            self._permission = PermissionState.unavailable
            raise AudioDeviceError(
                "AUDIO_DEVICE_UNAVAILABLE", "Audio device is unavailable."
            )
        sd = _load_sounddevice()
        device_arg = self._resolve_device_arg(device_id)
        try:
            sd.check_input_settings(  # type: ignore[attr-defined]
                device=device_arg,
                samplerate=self.format.sample_rate_hz,
                channels=self.format.channels,
                dtype="int16",
            )
        except Exception as exc:
            self._permission = PermissionState.unavailable
            raise AudioDeviceError(
                "AUDIO_DEVICE_UNAVAILABLE",
                "Audio device does not support 16 kHz mono PCM.",
            ) from exc
        self._permission = PermissionState.granted
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
        self.close()
        sd = _load_sounddevice()
        device_arg = self._resolve_device_arg(device_id)
        try:
            stream = sd.RawInputStream(  # type: ignore[attr-defined]
                samplerate=self.format.sample_rate_hz,
                channels=self.format.channels,
                dtype="int16",
                device=device_arg,
            )
            stream.start()
        except Exception as exc:
            raise AudioDeviceError(
                "AUDIO_DEVICE_UNAVAILABLE", "Audio device could not be opened."
            ) from exc
        self._stream = stream
        self._selected = device_id

    def read_chunks(
        self, *, session_id: str, duration_ms: int, chunk_ms: int = 20
    ) -> list[AudioChunk]:
        if type(duration_ms) is not int or duration_ms <= 0:
            raise ValueError("duration_ms must be a positive integer")
        if self._selected is None or self._stream is None:
            raise AudioDeviceError(
                "AUDIO_DEVICE_NOT_READY", "Audio device is not ready."
            )
        if self._permission is not PermissionState.granted:
            raise AudioDeviceError(
                "AUDIO_DEVICE_NOT_READY", "Audio device is not ready."
            )
        frames = duration_ms * (self.format.sample_rate_hz // 1000)
        try:
            data, _overflowed = self._stream.read(frames)  # type: ignore[attr-defined]
            pcm = bytes(data)
        except Exception as exc:
            self.close()
            raise AudioDeviceError(
                "AUDIO_DEVICE_LOST", "Audio device was lost mid-session."
            ) from exc
        if len(pcm) != duration_ms * 32:
            self.close()
            raise AudioDeviceError(
                "AUDIO_DEVICE_LOST", "Audio device returned an incomplete read."
            )
        return chunk_pcm(pcm, session_id=session_id, chunk_ms=chunk_ms)

    def close(self) -> None:
        """Stop and close the underlying input stream if open."""
        stream = self._stream
        self._stream = None
        self._selected = None
        if stream is not None:
            for method_name in ("stop", "close"):
                method = getattr(stream, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:
                        pass
