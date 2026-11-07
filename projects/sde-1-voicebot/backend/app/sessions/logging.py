"""Structured and redacted logging utilities for session operations."""

import json
import logging
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# Context variables for request tracing
current_correlation_id: ContextVar[str] = ContextVar(
    "current_correlation_id", default=""
)
current_request_id: ContextVar[str] = ContextVar("current_request_id", default="")
current_session_id: ContextVar[str] = ContextVar("current_session_id", default="")

# Redaction patterns
REDACTION_PATTERNS = [
    # Authorization header / Bearer tokens
    (re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE), "Bearer [REDACTED]"),
    # Token / secret / password query params or JSON keys
    (
        re.compile(
            r'("(?:token|secret|password|api_key|access_token|key)"\s*:\s*")(?:[^"\\]|\\.)*(")',
            re.IGNORECASE,
        ),
        r"\1[REDACTED]\2",
    ),
    (
        re.compile(
            r"((?:token|secret|password|api_key|access_token)=)[^\s&,;]+",
            re.IGNORECASE,
        ),
        r"\1[REDACTED]",
    ),
    # Raw PCM or binary audio byte representation
    (
        re.compile(r"(?:b'\\x[0-9a-fA-Fx\\]+'|bytes\(\d+\))"),
        "[REDACTED_AUDIO_BYTES]",
    ),
    # Raw transcript content leak patterns
    (
        re.compile(
            r'("(?:transcript|text)"\s*:\s*")(?:[^"\\]|\\.)*(")',
            re.IGNORECASE,
        ),
        r"\1[REDACTED_TEXT]\2",
    ),
    # Screen capture content patterns
    (
        re.compile(
            r'("(?:screen_context|image_bytes|frame_data)"\s*:\s*")(?:[^"\\]|\\.)*(")',
            re.IGNORECASE,
        ),
        r"\1[REDACTED_SCREEN]\2",
    ),
]


def redact_sensitive_data(message: str) -> str:
    """Sanitize message by redacting secrets, audio, transcripts, and screen content."""
    result = message
    for pattern, replacement in REDACTION_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


class StructuredRedactingFormatter(logging.Formatter):
    """Formats log records as structured, safe JSON with correlation IDs."""

    def format(self, record: logging.LogRecord) -> str:
        corr_id = getattr(record, "correlation_id", None) or current_correlation_id.get(
            ""
        )
        req_id = getattr(record, "request_id", None) or current_request_id.get("")
        sess_id = getattr(record, "session_id", None) or current_session_id.get("")

        raw_message = record.getMessage()
        safe_message = redact_sensitive_data(raw_message)

        # Do not leak raw exception stack traces to external logs
        safe_exc = None
        if record.exc_info:
            exc_type = record.exc_info[0]
            safe_exc = exc_type.__name__ if exc_type else "Exception"

        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": safe_message,
        }

        if corr_id:
            log_data["correlation_id"] = corr_id
        if req_id:
            log_data["request_id"] = req_id
        if sess_id:
            log_data["session_id"] = sess_id
        if safe_exc:
            log_data["exception_class"] = safe_exc

        return json.dumps(log_data)
