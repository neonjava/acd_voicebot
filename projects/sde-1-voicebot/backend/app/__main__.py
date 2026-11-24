"""Launcher for running the SDE 1 Voicebot backend application as a local sidecar."""

import uvicorn

from app.config import settings


def main() -> None:
    """Run uvicorn server on configured host and port with clean shutdown."""
    config = uvicorn.Config(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    server.run()


if __name__ == "__main__":
    main()
