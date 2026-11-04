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

        try:
            port_val = int(os.getenv("PORT", "8000"))
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

        return cls(
            mock_mode=mock_val,
            host=host_val,
            port=port_val,
            log_level=log_level_val,
            session_ttl_seconds=ttl_val,
            max_payload_bytes=max_payload_val,
            max_events_per_session=max_events_val,
        )


settings = Settings.from_env()
