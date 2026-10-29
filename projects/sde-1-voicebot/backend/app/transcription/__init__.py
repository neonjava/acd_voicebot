"""Speech-to-text / transcription package for Academiaai AI Voicebot."""

from app.transcription.accumulator import SegmentAccumulator
from app.transcription.adapter import TranscriptionAdapter
from app.transcription.mock import FakeTranscriber

__all__ = [
    "FakeTranscriber",
    "SegmentAccumulator",
    "TranscriptionAdapter",
]
