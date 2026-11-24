"""Speech-to-text / transcription package for Academiaai AI Voicebot."""

from app.transcription.accumulator import SegmentAccumulator
from app.transcription.adapter import TranscriptionAdapter
from app.transcription.config import TranscriptionConfig
from app.transcription.faster_whisper import FasterWhisperAdapter
from app.transcription.mock import FakeTranscriber
from app.transcription.orchestrator import TranscriptionOrchestrator
from app.transcription.preprocessing import (
    AudioPreprocessor,
    normalize_amplitude,
    resample_pcm,
)
from app.transcription.retry import RetryPolicy

__all__ = [
    "AudioPreprocessor",
    "FakeTranscriber",
    "FasterWhisperAdapter",
    "RetryPolicy",
    "SegmentAccumulator",
    "TranscriptionAdapter",
    "TranscriptionConfig",
    "TranscriptionOrchestrator",
    "normalize_amplitude",
    "resample_pcm",
]
