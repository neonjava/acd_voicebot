"""Tests for text-to-speech synthesizers, contracts, and configuration."""

from __future__ import annotations

import io
import wave
from typing import Any

import pytest

from app.tts import (
    MockSynthesizer,
    PiperSynthesizer,
    SpeechSynthesizer,
    TTSConfig,
    TTSTextTooLongError,
    TTSUnavailableError,
    get_synthesizer,
)


class TestMockSynthesizer:
    """Tests for deterministic MockSynthesizer."""

    def test_implements_speech_synthesizer_protocol(self) -> None:
        mock = MockSynthesizer()
        assert isinstance(mock, SpeechSynthesizer)

    def test_synthesizes_valid_16bit_mono_wav(self) -> None:
        mock = MockSynthesizer()
        wav_bytes = mock.synthesize("Hello from Jarvis voicebot.")

        assert isinstance(wav_bytes, bytes)
        assert len(wav_bytes) > 44  # WAV header is 44 bytes
        assert wav_bytes.startswith(b"RIFF")
        assert b"WAVE" in wav_bytes[:16]

        # Inspect with wave module
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            assert wf.getnchannels() == 1  # Mono
            assert wf.getsampwidth() == 2  # 16-bit
            assert wf.getframerate() == 16000
            assert wf.getnframes() > 0

    def test_refuses_text_exceeding_300_characters(self) -> None:
        mock = MockSynthesizer()
        long_text = "a" * 301
        with pytest.raises(TTSTextTooLongError, match="exceeds maximum allowed limit"):
            mock.synthesize(long_text)

    def test_accepts_exactly_300_characters(self) -> None:
        mock = MockSynthesizer()
        boundary_text = "a" * 300
        wav_bytes = mock.synthesize(boundary_text)
        assert isinstance(wav_bytes, bytes)
        assert len(wav_bytes) > 0

    def test_rejects_non_string_text(self) -> None:
        mock = MockSynthesizer()
        with pytest.raises(ValueError, match="text must be a string"):
            mock.synthesize(123)  # type: ignore[arg-type]


class TestPiperSynthesizer:
    """Tests for PiperSynthesizer with lazy loading and error handling."""

    def test_implements_speech_synthesizer_protocol(self) -> None:
        synth = PiperSynthesizer()
        assert isinstance(synth, SpeechSynthesizer)

    def test_refuses_text_exceeding_300_characters_before_model_load(self) -> None:
        synth = PiperSynthesizer()
        long_text = "b" * 301
        with pytest.raises(TTSTextTooLongError, match="exceeds maximum allowed limit"):
            synth.synthesize(long_text)

    def test_missing_voice_or_package_raises_tts_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """When piper is absent or model is missing, raises safe TTSUnavailableError."""
        cfg = TTSConfig(
            provider="piper",
            voice="non_existent_voice",
            cache_dir=str(tmp_path),
        )
        synth = PiperSynthesizer(config=cfg)

        with pytest.raises(TTSUnavailableError) as exc_info:
            synth.synthesize("Testing voice synthesis.")

        assert exc_info.value.error_code == "TTS_UNAVAILABLE"

        # Subsequent call re-raises the cached failure fast
        with pytest.raises(TTSUnavailableError):
            synth.synthesize("Second call.")

    def test_injected_voice_synthesizes_valid_wav_without_model_download(self) -> None:
        """Verify injected fake voice works without disk downloads or packages."""

        class FakeVoice:
            def synthesize(self, text: str, wav_file: Any) -> None:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                # Write 100 samples of 16-bit silence
                wav_file.writeframes(b"\x00\x00" * 100)

        synth = PiperSynthesizer(voice=FakeVoice())
        wav_bytes = synth.synthesize("Testing injected voice.")

        assert isinstance(wav_bytes, bytes)
        assert wav_bytes.startswith(b"RIFF")
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.getnframes() == 100


class TestTTSConfigAndFactory:
    """Tests for configuration resolution and synthesizer factory."""

    def test_config_validation(self) -> None:
        with pytest.raises(ValueError, match="Unknown TTS provider"):
            TTSConfig(provider="unsupported")  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="sample_rate must be a positive integer"):
            TTSConfig(sample_rate=-16000)

        with pytest.raises(
            ValueError, match="max_text_length must be a positive integer"
        ):
            TTSConfig(max_text_length=0)

    def test_from_env_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TTS_PROVIDER", "piper")
        monkeypatch.setenv("TTS_VOICE", "custom-voice")
        monkeypatch.setenv("TTS_SAMPLE_RATE", "22050")
        monkeypatch.setenv("TTS_CACHE_DIR", "/custom/cache")

        cfg = TTSConfig.from_env()
        assert cfg.provider == "piper"
        assert cfg.voice == "custom-voice"
        assert cfg.sample_rate == 22050
        assert cfg.cache_dir == "/custom/cache"

    def test_get_synthesizer_factory(self) -> None:
        mock_synth = get_synthesizer(TTSConfig(provider="mock"))
        assert isinstance(mock_synth, MockSynthesizer)

        piper_synth = get_synthesizer(TTSConfig(provider="piper"))
        assert isinstance(piper_synth, PiperSynthesizer)
