"""Run the deterministic audio stream without a microphone or audio playback."""

import argparse
import sys

from pydantic import ValidationError

from app.audio.chunker import chunk_pcm
from app.audio.source import make_fake_pcm
from app.contracts.audio import AudioError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show deterministic mock audio chunks")
    parser.add_argument("--session-id", default="session-demo")
    parser.add_argument("--duration-ms", type=int, default=1000)
    parser.add_argument("--chunk-ms", type=int, default=20)
    args = parser.parse_args(argv)

    try:
        pcm = make_fake_pcm(duration_ms=args.duration_ms)
        chunks = chunk_pcm(pcm, session_id=args.session_id, chunk_ms=args.chunk_ms)
    except (ValueError, ValidationError) as exc:
        # Do not copy exception text or input bytes into a user-facing error.
        error = AudioError(
            code="AUDIO_INVALID_INPUT",
            message_safe_for_user="Invalid mock audio settings.",
            retryable=False,
            correlation_id="correlation-demo",
            details_redacted={"reason": type(exc).__name__},
        )
        print(error.model_dump_json(), file=sys.stderr)
        return 2

    for chunk in chunks:
        print(
            f"sequence={chunk.sequence_id} start_ms={chunk.start_ms} "
            f"duration_ms={chunk.duration_ms} "
            f"format={chunk.format.encoding}/{chunk.format.sample_rate_hz}Hz/"
            f"{chunk.format.channels}ch bytes={len(chunk.pcm)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
