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
    assert cfg.launch_token is None


def test_valid_custom_environment():
    """Settings loaded from valid environment variables must apply."""
    env = {
        "MOCK_MODE": "false",
        "HOST": "127.0.0.1",
        "PORT": "9000",
        "LOG_LEVEL": "debug",
        "SESSION_TTL_SECONDS": "1800",
        "MAX_PAYLOAD_BYTES": "32768",
        "MAX_EVENTS_PER_SESSION": "500",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = Settings.from_env()
        assert cfg.mock_mode is False
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 9000
        assert cfg.log_level == "DEBUG"
        assert cfg.session_ttl_seconds == 1800
        assert cfg.max_payload_bytes == 32768
        assert cfg.max_events_per_session == 500


def test_host_other_than_127_0_0_1_rejected():
    """Server must bind only to 127.0.0.1; any other host is rejected."""
    with pytest.raises(ValidationError):
        Settings(host="0.0.0.0")

    with pytest.raises(ValidationError):
        Settings(host="192.168.1.100")

    with patch.dict(os.environ, {"HOST": "0.0.0.0"}, clear=True):
        with pytest.raises(ValidationError):
            Settings.from_env()


def test_voicebot_port_and_launch_token_from_env():
    """Settings reads VOICEBOT_PORT and VOICEBOT_LAUNCH_TOKEN from environment."""
    env = {
        "VOICEBOT_PORT": "8088",
        "VOICEBOT_LAUNCH_TOKEN": "my-secret-launch-token",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = Settings.from_env()
        assert cfg.port == 8088
        assert cfg.launch_token == "my-secret-launch-token"


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


@pytest.mark.asyncio
async def test_lifespan_ready_line_only_after_port_binds(capsys):
    """VOICEBOT_READY is printed only after port connection succeeds, not before."""
    import asyncio
    from unittest.mock import MagicMock

    from app.main import app, lifespan

    # 1. When port connection fails, VOICEBOT_READY is NOT printed
    with patch("socket.create_connection", side_effect=OSError("Connection refused")):
        async with lifespan(app):
            await asyncio.sleep(0.05)
            captured = capsys.readouterr()
            assert "VOICEBOT_READY" not in captured.out

    # 2. When port connection succeeds, VOICEBOT_READY is printed
    mock_sock = MagicMock()
    with patch("socket.create_connection", return_value=mock_sock):
        async with lifespan(app):
            await asyncio.sleep(0.05)
            captured = capsys.readouterr()
            assert "VOICEBOT_READY" in captured.out
