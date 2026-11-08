"""Tests for startup configuration validation and mock defaults (W5)."""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_default_settings():
    """Default settings must have mock_mode=True and safe defaults."""
    cfg = Settings()
    assert cfg.mock_mode is True
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8000
    assert cfg.log_level == "INFO"
    assert cfg.session_ttl_seconds == 3600
    assert cfg.max_payload_bytes == 65536
    assert cfg.max_events_per_session == 1000
    assert cfg.event_stream_chunk_ms == 20


def test_valid_custom_environment():
    """Settings loaded from valid environment variables must apply."""
    env = {
        "MOCK_MODE": "false",
        "HOST": "0.0.0.0",
        "PORT": "9000",
        "LOG_LEVEL": "debug",
        "SESSION_TTL_SECONDS": "1800",
        "MAX_PAYLOAD_BYTES": "32768",
        "MAX_EVENTS_PER_SESSION": "500",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = Settings.from_env()
        assert cfg.mock_mode is False
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 9000
        assert cfg.log_level == "DEBUG"
        assert cfg.session_ttl_seconds == 1800
        assert cfg.max_payload_bytes == 32768
        assert cfg.max_events_per_session == 500


def test_invalid_log_level_rejected():
    """Invalid log level must raise ValidationError."""
    with pytest.raises(ValidationError):
        Settings(log_level="INVALID_LEVEL")


def test_invalid_port_rejected():
    """Out of range port must raise ValidationError."""
    with pytest.raises(ValidationError):
        Settings(port=70000)

    with pytest.raises(ValidationError):
        Settings(port=0)


def test_non_integer_port_from_env_rejected():
    """Non-integer PORT in environment must fail clearly."""
    with patch.dict(os.environ, {"PORT": "not-a-port"}, clear=True):
        with pytest.raises(ValueError, match="PORT must be an integer"):
            Settings.from_env()


def test_invalid_ttl_rejected():
    """Negative or zero TTL must raise ValidationError."""
    with pytest.raises(ValidationError):
        Settings(session_ttl_seconds=0)

    with pytest.raises(ValidationError):
        Settings(session_ttl_seconds=-50)


def test_invalid_max_payload_rejected():
    """Negative or excessive max_payload_bytes must raise ValidationError."""
    with pytest.raises(ValidationError):
        Settings(max_payload_bytes=0)

    with pytest.raises(ValidationError):
        Settings(max_payload_bytes=20000000)
