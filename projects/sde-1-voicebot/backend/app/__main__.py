"""Launcher for running the SDE 1 Voicebot backend application."""

import uvicorn

from app.config import settings


def main() -> None:
    """Run uvicorn server on configured host and port."""
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
