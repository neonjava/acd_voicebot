"""Tests for structured logging and sensitive data redaction (W5)."""

import json
import logging

from app.sessions.logging import (
    StructuredRedactingFormatter,
    current_correlation_id,
    current_request_id,
    redact_sensitive_data,
)


def test_redact_sensitive_tokens_and_passwords():
    """Bearer tokens, passwords, and secrets must be redacted."""
    raw = (
        "User requested with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 "
        "and token=secret_value_123"
    )
    sanitized = redact_sensitive_data(raw)
    assert "eyJhbGci" not in sanitized
    assert "Bearer [REDACTED]" in sanitized
    assert "token=[REDACTED]" in sanitized


def test_redact_audio_bytes_and_pcm():
    """Raw audio bytes representations must be redacted."""
    raw = "Audio buffer contains b'\\x00\\x01\\x02\\x03' and bytes(32000)"
    sanitized = redact_sensitive_data(raw)
    assert "b'\\x00" not in sanitized
    assert "[REDACTED_AUDIO_BYTES]" in sanitized


def test_redact_transcript_text():
    """Spoken transcript text in json strings must be redacted."""
    raw = '{"event": "segment", "transcript": "Private medical discussion"}'
    sanitized = redact_sensitive_data(raw)
    assert "Private medical discussion" not in sanitized
    assert "[REDACTED_TEXT]" in sanitized


def test_redact_screen_context():
    """Screen context details must be redacted."""
    raw = '{"screen_context": "Financial bank account statement"}'
    sanitized = redact_sensitive_data(raw)
    assert "Financial bank account" not in sanitized
    assert "[REDACTED_SCREEN]" in sanitized


def test_structured_formatter_output():
    """StructuredRedactingFormatter produces valid JSON with metadata."""
    formatter = StructuredRedactingFormatter()
    current_correlation_id.set("corr-test-log-123")
    current_request_id.set("req-test-log-456")

    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Processed session with Bearer secret-auth-token",
        args=(),
        exc_info=None,
    )

    formatted = formatter.format(record)
    data = json.loads(formatted)

    assert data["level"] == "INFO"
    assert data["logger"] == "test.logger"
    assert data["correlation_id"] == "corr-test-log-123"
    assert data["request_id"] == "req-test-log-456"
    assert "secret-auth-token" not in data["message"]
    assert "Bearer [REDACTED]" in data["message"]


def test_structured_formatter_hides_raw_stack_trace():
    """Exceptions in log records only include the class name, never raw trace."""
    formatter = StructuredRedactingFormatter()
    try:
        raise ValueError("Internal database connection error")
    except ValueError:
        import sys

        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test.logger",
        level=logging.ERROR,
        pathname=__file__,
        lineno=20,
        msg="An error occurred during session processing",
        args=(),
        exc_info=exc_info,
    )

    formatted = formatter.format(record)
    data = json.loads(formatted)

    assert data["level"] == "ERROR"
    assert data["exception_class"] == "ValueError"
    # Ensure raw trace is not dumped into message
    assert "Traceback" not in formatted
