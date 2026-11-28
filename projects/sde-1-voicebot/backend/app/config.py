"""Application configuration validated at startup."""

import os

from pydantic import Field, field_validator

from app.contracts.common import ContractModel

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(ContractModel):
    """Configuration loaded from environment variables with mock defaults."""

    mock_mode: bool = Field(default=True)
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = Field(default="INFO")
    session_ttl_seconds: int = Field(default=3600, gt=0)
    max_payload_bytes: int = Field(default=65536, gt=0, le=10485760)
    max_events_per_session: int = Field(default=1000, gt=0)
    event_stream_chunk_ms: int = Field(default=20, gt=0)
    launch_token: str | None = Field(default=None)
    rate_limit_requests: int = Field(default=100, gt=0)
    rate_limit_window_seconds: int = Field(default=60, gt=0)
    tts_enabled: bool = Field(default=False)
    browser_timeout_seconds: float = Field(default=15.0, gt=0)
    notes_dirs: str | None = Field(default=None)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        if value != "127.0.0.1":
            raise ValueError(
                f"Server must bind only to 127.0.0.1 for local isolation, got '{value}'"
            )
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        upper = value.upper()
        if upper not in VALID_LOG_LEVELS:
            raise ValueError(
                f"Invalid log_level '{value}'. Expected one of: "
                f"{', '.join(sorted(VALID_LOG_LEVELS))}"
            )
        return upper

    @classmethod
    def from_env(cls) -> "Settings":
        mock_raw = os.getenv("MOCK_MODE", "true").lower()
        mock_val = mock_raw in ("1", "true", "yes", "on")

        host_val = os.getenv("HOST", "127.0.0.1")

        port_str = os.getenv("VOICEBOT_PORT") or os.getenv("PORT", "8000")
        try:
            port_val = int(port_str)
        except ValueError as err:
            raise ValueError(f"PORT must be an integer: {err}") from err

        log_level_val = os.getenv("LOG_LEVEL", "INFO")

        try:
            ttl_val = int(os.getenv("SESSION_TTL_SECONDS", "3600"))
        except ValueError as err:
            raise ValueError(f"SESSION_TTL_SECONDS must be an integer: {err}") from err

        try:
            max_payload_val = int(os.getenv("MAX_PAYLOAD_BYTES", "65536"))
        except ValueError as err:
            raise ValueError(f"MAX_PAYLOAD_BYTES must be an integer: {err}") from err

        try:
            max_events_val = int(os.getenv("MAX_EVENTS_PER_SESSION", "1000"))
        except ValueError as err:
            raise ValueError(
                f"MAX_EVENTS_PER_SESSION must be an integer: {err}"
            ) from err

        token_raw = os.getenv("VOICEBOT_LAUNCH_TOKEN")
        launch_token_val = (
            token_raw.strip() if token_raw and token_raw.strip() else None
        )

        try:
            rate_limit_req_val = int(os.getenv("VOICEBOT_RATE_LIMIT_REQUESTS", "100"))
        except ValueError as err:
            raise ValueError(
                f"VOICEBOT_RATE_LIMIT_REQUESTS must be an integer: {err}"
            ) from err

        try:
            rate_limit_win_val = int(os.getenv("VOICEBOT_RATE_LIMIT_WINDOW", "60"))
        except ValueError as err:
            raise ValueError(
                f"VOICEBOT_RATE_LIMIT_WINDOW must be an integer: {err}"
            ) from err

        tts_raw = os.getenv("TTS_ENABLED", "false").lower()
        tts_val = tts_raw in ("1", "true", "yes", "on")

        try:
            browser_timeout_val = float(os.getenv("VOICEBOT_BROWSER_TIMEOUT", "15.0"))
        except ValueError as err:
            raise ValueError(
                f"VOICEBOT_BROWSER_TIMEOUT must be a number: {err}"
            ) from err

        notes_dirs_val = os.getenv("REASONING_NOTES_DIRS")

        return cls(
            mock_mode=mock_val,
            host=host_val,
            port=port_val,
            log_level=log_level_val,
            session_ttl_seconds=ttl_val,
            max_payload_bytes=max_payload_val,
            max_events_per_session=max_events_val,
            launch_token=launch_token_val,
            rate_limit_requests=rate_limit_req_val,
            rate_limit_window_seconds=rate_limit_win_val,
            tts_enabled=tts_val,
            browser_timeout_seconds=browser_timeout_val,
            notes_dirs=notes_dirs_val,
        )


settings = Settings.from_env()
