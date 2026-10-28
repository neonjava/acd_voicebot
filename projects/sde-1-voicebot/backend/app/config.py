"""Application configuration validated at startup."""

import os

from pydantic import Field

from app.contracts.common import ContractModel


class Settings(ContractModel):
    """Configuration loaded from environment variables with mock defaults."""

    mock_mode: bool = Field(default=True)
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = Field(default="INFO")

    @classmethod
    def from_env(cls) -> "Settings":
        mock_val = os.getenv("MOCK_MODE", "true").lower() in ("1", "true", "yes", "on")
        host_val = os.getenv("HOST", "127.0.0.1")
        port_val = int(os.getenv("PORT", "8000"))
        log_level_val = os.getenv("LOG_LEVEL", "INFO")
        return cls(
            mock_mode=mock_val,
            host=host_val,
            port=port_val,
            log_level=log_level_val,
        )


settings = Settings.from_env()
