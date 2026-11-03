"""Audio preprocessing utilities: amplitude normalization and resampling.

Provides deterministic in-memory preprocessing for PCM s16le mono audio:
- normalize_amplitude: scales sample amplitudes to a target peak without clipping.
- resample_pcm: linear interpolation resampling to standard sample rates (e.g. 16kHz).
- preprocess_chunk: normalizes an AudioChunk while keeping contracts intact.
- resample_to_chunks: converts non-16kHz PCM to standard 16kHz AudioChunks.
"""

import struct
from collections.abc import Sequence

from app.audio.chunker import chunk_pcm
from app.contracts.audio import AudioChunk

BYTES_PER_SAMPLE = 2  # 16-bit signed integer (pcm_s16le)
MAX_AMPLITUDE_S16 = 32767
MIN_AMPLITUDE_S16 = -32768


def normalize_amplitude(pcm: bytes, *, target_peak: float = 0.95) -> bytes:
    """Normalize PCM s16le mono audio to a target peak ratio in (0.0, 1.0].

    Pure silence (all zeros) is returned unmodified. Samples are scaled linearly
    and clamped to valid 16-bit signed bounds [-32768, 32767].
    """
    if type(pcm) is not bytes:
        raise ValueError("pcm must be bytes")
    if len(pcm) % BYTES_PER_SAMPLE != 0:
        raise ValueError("pcm byte length must be a multiple of 2 (16-bit samples)")
    if type(target_peak) not in (int, float) or target_peak <= 0.0 or target_peak > 1.0:
        raise ValueError("target_peak must be a float in (0.0, 1.0]")

    if not pcm:
        return b""

    sample_count = len(pcm) // BYTES_PER_SAMPLE
    # Unpack all 16-bit signed integers
    fmt = f"<{sample_count}h"
    samples = struct.unpack(fmt, pcm)

    max_val = max(abs(s) for s in samples)
    if max_val == 0:
        return pcm

    target_max = target_peak * MAX_AMPLITUDE_S16
    scale = target_max / max_val

    # Scale each sample and clamp
    scaled_samples = [
        max(MIN_AMPLITUDE_S16, min(MAX_AMPLITUDE_S16, int(round(s * scale))))
        for s in samples
    ]
    return struct.pack(fmt, *scaled_samples)


def resample_pcm(pcm: bytes, from_rate_hz: int, to_rate_hz: int = 16000) -> bytes:
    """Resample PCM s16le mono audio from one sample rate to another.

    Uses deterministic linear interpolation.
    """
    if type(pcm) is not bytes:
        raise ValueError("pcm must be bytes")
    if len(pcm) % BYTES_PER_SAMPLE != 0:
        raise ValueError("pcm byte length must be a multiple of 2 (16-bit samples)")
    if type(from_rate_hz) is not int or from_rate_hz <= 0:
        raise ValueError("from_rate_hz must be a positive integer")
    if type(to_rate_hz) is not int or to_rate_hz <= 0:
        raise ValueError("to_rate_hz must be a positive integer")

    if not pcm:
        return b""

    if from_rate_hz == to_rate_hz:
        return pcm

    in_count = len(pcm) // BYTES_PER_SAMPLE
    fmt_in = f"<{in_count}h"
    in_samples = struct.unpack(fmt_in, pcm)

    # Compute target output sample count
    out_count = int(round(in_count * to_rate_hz / from_rate_hz))
    if out_count == 0:
        return b""

    out_samples: list[int] = []
    ratio = from_rate_hz / to_rate_hz

    for out_idx in range(out_count):
        src_pos = out_idx * ratio
        idx_low = int(src_pos)
        idx_high = min(idx_low + 1, in_count - 1)
        frac = src_pos - idx_low

        s_low = in_samples[idx_low]
        s_high = in_samples[idx_high]
        interpolated = s_low + frac * (s_high - s_low)
        clamped = max(
            MIN_AMPLITUDE_S16, min(MAX_AMPLITUDE_S16, int(round(interpolated)))
        )
        out_samples.append(clamped)

    fmt_out = f"<{out_count}h"
    return struct.pack(fmt_out, *out_samples)


class AudioPreprocessor:
    """Configurable audio preprocessor for normalization and rate conversion."""

    def __init__(
        self,
        *,
        normalize: bool = True,
        target_peak: float = 0.95,
        target_rate_hz: int = 16000,
    ) -> None:
        if type(normalize) is not bool:
            raise ValueError("normalize must be a boolean")
        if (
            type(target_peak) not in (int, float)
            or target_peak <= 0.0
            or target_peak > 1.0
        ):
            raise ValueError("target_peak must be a float in (0.0, 1.0]")
        if type(target_rate_hz) is not int or target_rate_hz <= 0:
            raise ValueError("target_rate_hz must be a positive integer")

        self.normalize = normalize
        self.target_peak = float(target_peak)
        self.target_rate_hz = target_rate_hz

    def process_chunk(self, chunk: AudioChunk) -> AudioChunk:
        """Preprocess single AudioChunk (normalization preserves 16kHz contract)."""
        if not isinstance(chunk, AudioChunk):
            raise TypeError("chunk must be an instance of AudioChunk")

        if not self.normalize:
            return chunk

        normalized_pcm = normalize_amplitude(chunk.pcm, target_peak=self.target_peak)
        return AudioChunk(
            session_id=chunk.session_id,
            sequence_id=chunk.sequence_id,
            start_ms=chunk.start_ms,
            duration_ms=chunk.duration_ms,
            format=chunk.format,
            pcm=normalized_pcm,
        )

    def process_chunks(self, chunks: Sequence[AudioChunk]) -> list[AudioChunk]:
        """Preprocess a sequence of AudioChunk objects."""
        return [self.process_chunk(chunk) for chunk in chunks]

    def convert_external_audio(
        self,
        pcm: bytes,
        *,
        from_rate_hz: int,
        session_id: str,
        chunk_ms: int = 20,
    ) -> list[AudioChunk]:
        """Convert arbitrary sample rate PCM into validated 16kHz chunks."""
        if from_rate_hz != self.target_rate_hz:
            pcm = resample_pcm(
                pcm, from_rate_hz=from_rate_hz, to_rate_hz=self.target_rate_hz
            )

        if self.normalize:
            pcm = normalize_amplitude(pcm, target_peak=self.target_peak)

        return chunk_pcm(pcm, session_id=session_id, chunk_ms=chunk_ms)
