"""Split supported PCM into timestamped, ordered AudioChunk objects."""

from app.contracts.audio import AudioChunk, AudioFormat

BYTES_PER_MS = 32  # 16 samples/ms × 2 bytes/sample × one channel.


def chunk_pcm(pcm: bytes, *, session_id: str, chunk_ms: int = 20) -> list[AudioChunk]:
    """Chunk whole-millisecond PCM; keep a shorter final chunk if needed.

    Empty bytes produce no chunks. A partial 16-bit sample or partial
    millisecond is invalid because AudioChunk.duration_ms is an integer.
    """
    if type(pcm) is not bytes:
        raise ValueError("pcm must be bytes")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id must be a nonempty string")
    if type(chunk_ms) is not int or chunk_ms <= 0:
        raise ValueError("chunk_ms must be a positive integer")
    if len(pcm) % 2:
        raise ValueError("pcm ends with an incomplete 16-bit sample")
    if len(pcm) % BYTES_PER_MS:
        raise ValueError("pcm duration must be a whole number of milliseconds")

    total_ms = len(pcm) // BYTES_PER_MS
    chunks: list[AudioChunk] = []
    for sequence_id, start_ms in enumerate(range(0, total_ms, chunk_ms)):
        duration_ms = min(chunk_ms, total_ms - start_ms)
        first_byte = start_ms * BYTES_PER_MS
        final_byte = first_byte + duration_ms * BYTES_PER_MS
        chunks.append(
            AudioChunk(
                session_id=session_id,
                sequence_id=sequence_id,
                start_ms=start_ms,
                duration_ms=duration_ms,
                format=AudioFormat(),
                pcm=pcm[first_byte:final_byte],
            )
        )
    return chunks
