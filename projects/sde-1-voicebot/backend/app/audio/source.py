"""Deterministic in-memory PCM source for Week 1 mock mode."""


def make_fake_pcm(*, duration_ms: int = 1000) -> bytes:
    """Return 16 kHz mono signed 16-bit little-endian synthetic audio.

    The integer pattern is repeatable across machines and runs. No microphone,
    network, clock, random source or file is used.
    """
    if type(duration_ms) is not int or duration_ms < 0:
        raise ValueError("duration_ms must be a nonnegative integer")

    sample_count = duration_ms * 16
    return b"".join(
        (((index * 257) % 65536) - 32768).to_bytes(2, "little", signed=True)
        for index in range(sample_count)
    )
