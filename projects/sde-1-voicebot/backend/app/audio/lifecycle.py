"""Audio-capture lifecycle; independent of W5's backend session lifecycle."""

from enum import Enum

from app.audio.buffer import BoundedAudioBuffer
from app.audio.device import AudioDevice, AudioDeviceError, PermissionState
from app.contracts.audio import AudioChunk


class CaptureState(str, Enum):
    created = "created"
    active = "active"
    paused = "paused"
    stopped = "stopped"


class AudioCaptureController:
    def __init__(
        self, *, session_id: str, device: AudioDevice, buffer: BoundedAudioBuffer
    ) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a nonempty string")
        self.session_id = session_id
        self.device = device
        self.buffer = buffer
        self.state = CaptureState.created
        self._next_sequence = 0
        self._next_start_ms = 0

    def start(self, device_id: str) -> None:
        if self.state is not CaptureState.created:
            raise ValueError("capture can only start from created")
        permission = self.device.request_permission(device_id)
        if permission is not PermissionState.granted:
            raise AudioDeviceError(
                "AUDIO_PERMISSION_DENIED", "Audio permission was denied."
            )
        self.device.select_device(device_id)
        self.state = CaptureState.active

    def pause(self) -> None:
        if self.state is not CaptureState.active:
            raise ValueError("capture can only pause while active")
        self.state = CaptureState.paused

    def resume(self) -> None:
        if self.state is not CaptureState.paused:
            raise ValueError("capture can only resume while paused")
        self.state = CaptureState.active

    def stop(self) -> None:
        if self.state is CaptureState.stopped:
            raise ValueError("capture is already stopped")
        self.buffer.release()
        self.state = CaptureState.stopped

    def produce(self, *, duration_ms: int, chunk_ms: int = 20) -> int:
        """Generate mock chunks; return the number retained by the buffer."""
        if self.state is not CaptureState.active:
            raise ValueError("capture must be active to produce audio")
        chunks = self.device.read_chunks(
            session_id=self.session_id, duration_ms=duration_ms, chunk_ms=chunk_ms
        )
        retained = 0
        for chunk in chunks:
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
