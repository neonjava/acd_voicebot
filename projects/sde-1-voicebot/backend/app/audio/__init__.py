"""W1 audio capture, VAD, wake-word gating, and speech-event pipeline."""

from app.audio.buffer import BoundedAudioBuffer
from app.audio.chunker import chunk_pcm
from app.audio.config import (
    AudioConfig,
    create_audio_device,
    create_vad,
    create_wake_word_detector,
)
from app.audio.device import (
    AudioDevice,
    AudioDeviceError,
    MockAudioDevice,
    PermissionState,
    SoundDeviceMicrophone,
)
from app.audio.lifecycle import AudioCaptureController, CaptureState
from app.audio.pipeline import (
    PipelineStepResult,
    SpeechPipeline,
    spans_to_speech_events,
    to_speech_envelope,
)
from app.audio.source import make_fake_pcm
from app.audio.vad import MockVAD, SileroVAD, SpeechSpan, VoiceActivityDetector
from app.audio.wake import (
    MockWakeWordDetector,
    OpenWakeWordDetector,
    WakeDetection,
    WakeWordDetector,
    make_wake_pcm,
)

__all__ = [
    "AudioCaptureController",
    "AudioConfig",
    "AudioDevice",
    "AudioDeviceError",
    "BoundedAudioBuffer",
    "CaptureState",
    "MockAudioDevice",
    "MockVAD",
    "SileroVAD",
    "MockWakeWordDetector",
    "OpenWakeWordDetector",
    "PermissionState",
    "PipelineStepResult",
    "SoundDeviceMicrophone",
    "SpeechPipeline",
    "SpeechSpan",
    "VoiceActivityDetector",
    "WakeDetection",
    "WakeWordDetector",
    "chunk_pcm",
    "create_audio_device",
    "create_vad",
    "create_wake_word_detector",
    "make_fake_pcm",
    "make_wake_pcm",
    "spans_to_speech_events",
    "to_speech_envelope",
]
