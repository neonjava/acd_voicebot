"""Tests for audio preprocessing (normalization and resampling)."""

import struct

import pytest

from app.contracts.audio import AudioChunk, AudioFormat
from app.transcription.preprocessing import (
    AudioPreprocessor,
    normalize_amplitude,
    resample_pcm,
)


def _make_sample_pcm(samples: list[int]) -> bytes:
    return struct.pack(f"<{len(samples)}h", *samples)


class TestNormalizeAmplitude:
    def test_normalize_scales_quiet_audio_to_target_peak(self) -> None:
        # Peak is 1000 out of 32767
        raw = _make_sample_pcm([100, -500, 1000, 0])
        normalized = normalize_amplitude(raw, target_peak=0.50)
        unpacked = struct.unpack(f"<{len(normalized) // 2}h", normalized)
        # 0.50 * 32767 = 16383.5 -> 16384
        assert max(abs(s) for s in unpacked) == 16384

    def test_normalize_preserves_pure_silence(self) -> None:
        silence = _make_sample_pcm([0, 0, 0, 0])
        normalized = normalize_amplitude(silence, target_peak=0.95)
        assert normalized == silence

    def test_normalize_empty_bytes_returns_empty(self) -> None:
        assert normalize_amplitude(b"", target_peak=0.90) == b""

    def test_normalize_prevents_clipping(self) -> None:
        raw = _make_sample_pcm([32767, -32768, 16000])
        normalized = normalize_amplitude(raw, target_peak=1.0)
        unpacked = struct.unpack(f"<{len(normalized) // 2}h", normalized)
        assert all(-32768 <= s <= 32767 for s in unpacked)

    @pytest.mark.parametrize("invalid_pcm", ["string", 123, None, bytearray(10)])
    def test_normalize_rejects_non_bytes(self, invalid_pcm: object) -> None:
        with pytest.raises(ValueError, match="pcm must be bytes"):
            normalize_amplitude(invalid_pcm, target_peak=0.90)  # type: ignore

    def test_normalize_rejects_odd_byte_length(self) -> None:
        with pytest.raises(ValueError, match="multiple of 2"):
            normalize_amplitude(b"\x00\x01\x02", target_peak=0.90)

    @pytest.mark.parametrize("invalid_peak", [0.0, -0.1, 1.01, 2.0, "0.5", None])
    def test_normalize_rejects_invalid_target_peak(self, invalid_peak: object) -> None:
        with pytest.raises(ValueError, match="target_peak must be a float in"):
            normalize_amplitude(b"\x00\x00", target_peak=invalid_peak)  # type: ignore


class TestResamplePcm:
    def test_resample_identity(self) -> None:
        pcm = _make_sample_pcm([100, 200, 300, 400])
        resampled = resample_pcm(pcm, from_rate_hz=16000, to_rate_hz=16000)
        assert resampled == pcm

    def test_resample_empty_bytes_returns_empty(self) -> None:
        assert resample_pcm(b"", from_rate_hz=8000, to_rate_hz=16000) == b""

    def test_resample_up_doubles_sample_count(self) -> None:
        # 8kHz -> 16kHz should double sample count
        pcm = _make_sample_pcm([1000, 2000, 3000, 4000])  # 4 samples = 8 bytes
        resampled = resample_pcm(pcm, from_rate_hz=8000, to_rate_hz=16000)
        assert len(resampled) == 16  # 8 samples = 16 bytes

    def test_resample_down_halves_sample_count(self) -> None:
        # 32kHz -> 16kHz should halve sample count
        pcm = _make_sample_pcm([100, 200, 300, 400, 500, 600])  # 6 samples = 12 bytes
        resampled = resample_pcm(pcm, from_rate_hz=32000, to_rate_hz=16000)
        assert len(resampled) == 6  # 3 samples = 6 bytes

    @pytest.mark.parametrize("invalid_rate", [0, -1, 1.5, "16000", None])
    def test_resample_rejects_invalid_rates(self, invalid_rate: object) -> None:
        with pytest.raises(ValueError, match="positive integer"):
            resample_pcm(b"\x00\x00", from_rate_hz=invalid_rate, to_rate_hz=16000)  # type: ignore
        with pytest.raises(ValueError, match="positive integer"):
            resample_pcm(b"\x00\x00", from_rate_hz=16000, to_rate_hz=invalid_rate)  # type: ignore

    def test_resample_rejects_odd_byte_length(self) -> None:
        with pytest.raises(ValueError, match="multiple of 2"):
            resample_pcm(b"\x00\x01\x02", from_rate_hz=8000, to_rate_hz=16000)


class TestAudioPreprocessor:
    def test_preprocessor_normalizes_audio_chunk(self) -> None:
        preprocessor = AudioPreprocessor(normalize=True, target_peak=0.80)
        raw_pcm = _make_sample_pcm([1000] * 320)  # 20ms at 16kHz = 640 bytes
        chunk = AudioChunk(
            session_id="sess-pre",
            sequence_id=0,
            start_ms=0,
            duration_ms=20,
            format=AudioFormat(),
            pcm=raw_pcm,
        )
        processed = preprocessor.process_chunk(chunk)
        assert processed.session_id == chunk.session_id
        assert processed.sequence_id == chunk.sequence_id
        assert len(processed.pcm) == len(chunk.pcm)
        unpacked = struct.unpack(f"<{len(processed.pcm) // 2}h", processed.pcm)
        assert max(abs(s) for s in unpacked) == int(round(0.80 * 32767))

    def test_preprocessor_skip_normalization_when_disabled(self) -> None:
        preprocessor = AudioPreprocessor(normalize=False)
        raw_pcm = _make_sample_pcm([1000] * 320)
        chunk = AudioChunk(
            session_id="sess-pre",
            sequence_id=0,
            start_ms=0,
            duration_ms=20,
            format=AudioFormat(),
            pcm=raw_pcm,
        )
        processed = preprocessor.process_chunk(chunk)
        assert processed.pcm == raw_pcm

    def test_convert_external_audio_to_chunks(self) -> None:
        preprocessor = AudioPreprocessor(normalize=True, target_peak=0.90)
        # 8000Hz PCM for 1000ms = 8000 samples = 16000 bytes
        pcm_8k = struct.pack("<8000h", *([500] * 8000))
        chunks = preprocessor.convert_external_audio(
            pcm_8k, from_rate_hz=8000, session_id="sess-ext", chunk_ms=20
        )
        # Resampled to 16000Hz (1000ms) -> 50 chunks of 20ms
        assert len(chunks) == 50
        assert all(isinstance(c, AudioChunk) for c in chunks)
        assert all(c.duration_ms == 20 for c in chunks)
        assert all(c.format.sample_rate_hz == 16000 for c in chunks)

    def test_preprocessor_invalid_config(self) -> None:
        with pytest.raises(ValueError, match="normalize must be a boolean"):
            AudioPreprocessor(normalize="yes")  # type: ignore
        with pytest.raises(ValueError, match="target_peak must be a float"):
            AudioPreprocessor(target_peak=0.0)
        with pytest.raises(
            ValueError, match="target_rate_hz must be a positive integer"
        ):
            AudioPreprocessor(target_rate_hz=-16000)

    def test_process_chunk_type_check(self) -> None:
        preprocessor = AudioPreprocessor()
        with pytest.raises(TypeError, match="instance of AudioChunk"):
            preprocessor.process_chunk("not a chunk")  # type: ignore
