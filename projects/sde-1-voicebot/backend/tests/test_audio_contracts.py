"""Day 1 checks using the shared contracts supplied by W5."""

import pytest
from pydantic import ValidationError

from app.contracts.audio import AudioChunk, AudioError, AudioFormat


def valid_chunk(**changes: object) -> AudioChunk:
    fields = {
        "session_id": "session-demo",
        "sequence_id": 0,
        "start_ms": 0,
        "duration_ms": 20,
        "format": AudioFormat(),
        "pcm": bytes(640),
    }
    fields.update(changes)
    return AudioChunk.model_validate(fields)


def test_supported_format_and_chunk():
    chunk = valid_chunk()
    assert chunk.format == AudioFormat(
        sample_rate_hz=16000, channels=1, encoding="pcm_s16le"
    )
    assert chunk.sequence_id == 0
    assert chunk.start_ms == 0
    assert len(chunk.pcm) == 640


@pytest.mark.parametrize(
    "changes",
    [
        {"sample_rate_hz": 44100},
        {"channels": 2},
        {"channels": True},
        {"encoding": "pcm_s16be"},
    ],
)
def test_unsupported_format_is_rejected(changes):
    with pytest.raises(ValidationError):
        AudioFormat.model_validate(changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"session_id": ""},
        {"sequence_id": -1},
        {"sequence_id": True},
        {"start_ms": -1},
        {"duration_ms": 0},
        {"pcm": b""},
        {"pcm": bytes(639)},
        {"pcm": bytes(642)},
        {"format": {"sample_rate_hz": 48000}},
    ],
)
def test_invalid_chunk_is_rejected(changes):
    with pytest.raises(ValidationError):
        valid_chunk(**changes)


def test_audio_error_has_safe_shared_fields():
    error = AudioError(
        code="AUDIO_INVALID_CHUNK",
        message_safe_for_user="Invalid audio chunk.",
        retryable=False,
        correlation_id="correlation-demo",
        details_redacted={},
    )
    assert error.code == "AUDIO_INVALID_CHUNK"
    assert error.correlation_id == "correlation-demo"


def test_error_code_requires_audio_prefix():
    with pytest.raises(ValidationError):
        AudioError(
            code="INVALID_CHUNK",
            message_safe_for_user="Invalid audio chunk.",
            retryable=False,
            correlation_id="correlation-demo",
            details_redacted={},
        )
