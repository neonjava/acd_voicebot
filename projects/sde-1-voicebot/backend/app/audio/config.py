"""Audio pipeline configuration and factory helpers (mock-first defaults)."""

import os
from math import isfinite
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, field_validator

from app.audio.device import AudioDevice, MockAudioDevice, SoundDeviceMicrophone
from app.audio.vad import MockVAD, SileroVAD, VoiceActivityDetector
from app.audio.wake import MockWakeWordDetector, OpenWakeWordDetector, WakeWordDetector
from app.contracts.common import ContractModel


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _parse_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _parse_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a float") from exc


class AudioConfig(ContractModel):
    """Configuration for audio device selection, wake gate, VAD, and recovery."""

    audio_source: Literal["mock", "mic"] = "mock"
    wake_required: StrictBool = True
    wake_provider: Literal["auto", "mock", "openwakeword"] = "auto"
    wake_word: str = Field(default="hey_jarvis", min_length=1, pattern=r"\S")
    wake_threshold: float = 0.5
    silence_timeout_ms: StrictInt = Field(default=2000, gt=0)
    speech_end_silence_ms: StrictInt = Field(default=400, gt=0)
    # One utterance is cut here; bounds memory and the Silero score cache, and
    # matches Whisper's 30 s window.
    max_utterance_ms: StrictInt = Field(default=30_000, gt=0, le=35_000)
    vad_provider: Literal["auto", "mock", "silero"] = "auto"
    vad_threshold: float = 0.1
    vad_min_speech_ms: StrictInt = Field(default=40, gt=0)
    chunk_ms: StrictInt = Field(default=20, gt=0)
    reconnect_max_attempts: StrictInt = Field(default=3, ge=0)
    reconnect_backoff_ms: StrictInt = Field(default=50, ge=0)
    mic_device: str | None = Field(default=None, min_length=1, pattern=r"\S")

    @field_validator("wake_threshold", "vad_threshold", mode="before")
    @classmethod
    def validate_unit_float(cls, value: object) -> float:
        if type(value) not in (int, float) or not isfinite(value):
            raise ValueError("threshold must be a finite number")
        if not 0.0 <= value <= 1.0:
            raise ValueError("threshold must be between zero and one")
        return float(value)

    @classmethod
    def from_env(cls) -> "AudioConfig":
        """Load audio configuration from environment variables with mock defaults."""
        source = os.getenv("AUDIO_SOURCE", "mock").strip().lower()
        wake_provider = os.getenv("AUDIO_WAKE_PROVIDER", "auto").strip().lower()
        vad_provider = os.getenv("AUDIO_VAD_PROVIDER", "auto").strip().lower()
        mic_device = os.getenv("AUDIO_MIC_DEVICE")
        return cls(
            audio_source=source,  # type: ignore[arg-type]
            wake_required=_parse_bool_env("AUDIO_WAKE_REQUIRED", True),
            wake_provider=wake_provider,  # type: ignore[arg-type]
            wake_word=os.getenv("AUDIO_WAKE_WORD", "hey_jarvis"),
            wake_threshold=_parse_float_env("AUDIO_WAKE_THRESHOLD", 0.5),
            silence_timeout_ms=_parse_int_env("AUDIO_SILENCE_TIMEOUT_MS", 2000),
            speech_end_silence_ms=_parse_int_env("AUDIO_SPEECH_END_SILENCE_MS", 400),
            max_utterance_ms=_parse_int_env("AUDIO_MAX_UTTERANCE_MS", 30_000),
            vad_provider=vad_provider,  # type: ignore[arg-type]
            vad_threshold=_parse_float_env("AUDIO_VAD_THRESHOLD", 0.1),
            vad_min_speech_ms=_parse_int_env("AUDIO_VAD_MIN_SPEECH_MS", 40),
            chunk_ms=_parse_int_env("AUDIO_CHUNK_MS", 20),
            reconnect_max_attempts=_parse_int_env("AUDIO_RECONNECT_MAX_ATTEMPTS", 3),
            reconnect_backoff_ms=_parse_int_env("AUDIO_RECONNECT_BACKOFF_MS", 50),
            mic_device=(
                mic_device.strip() if mic_device and mic_device.strip() else None
            ),
        )


def create_audio_device(config: AudioConfig | None = None) -> AudioDevice:
    """Return MockAudioDevice by default or SoundDeviceMicrophone for 'mic'."""
    cfg = config if config is not None else AudioConfig()
    if cfg.audio_source == "mock":
        return MockAudioDevice()
    return SoundDeviceMicrophone(device=cfg.mic_device)


def create_wake_word_detector(config: AudioConfig | None = None) -> WakeWordDetector:
    """Build the configured wake-word detector without eager audio extra imports."""
    cfg = config if config is not None else AudioConfig()
    provider = cfg.wake_provider
    if provider == "auto":
        provider = "openwakeword" if cfg.audio_source == "mic" else "mock"
    if provider == "mock":
        return MockWakeWordDetector(
            wake_word=cfg.wake_word,
            threshold=cfg.wake_threshold,
        )
    return OpenWakeWordDetector(
        wake_word=cfg.wake_word,
        threshold=cfg.wake_threshold,
    )


def create_vad(config: AudioConfig | None = None) -> VoiceActivityDetector:
    """Energy MockVAD for mock audio; Silero VAD for a real microphone.

    Real speech is far quieter than the synthetic fixtures, so the energy
    threshold that suits mock audio misses most real words. ``auto`` picks
    Silero whenever ``audio_source`` is ``"mic"``. Silero uses its own 0.5
    probability threshold and 100 ms minimum speech.
    """
    cfg = config if config is not None else AudioConfig()
    provider = cfg.vad_provider
    if provider == "auto":
        provider = "silero" if cfg.audio_source == "mic" else "mock"
    if provider == "silero":
        return SileroVAD()
    return MockVAD(threshold=cfg.vad_threshold, min_speech_ms=cfg.vad_min_speech_ms)
