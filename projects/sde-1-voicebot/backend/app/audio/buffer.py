"""Finite audio buffer that drops newest chunks when full or late."""

from collections import deque

from app.contracts.audio import AudioChunk


class BoundedAudioBuffer:
    def __init__(self, *, capacity_chunks: int) -> None:
        if type(capacity_chunks) is not int or capacity_chunks <= 0:
            raise ValueError("capacity_chunks must be a positive integer")
        self.capacity_chunks = capacity_chunks
        self._chunks: deque[AudioChunk] = deque()
        self._session_id: str | None = None
        self._last_sequence: int | None = None
        self._last_end_ms: int | None = None
        self.dropped_chunks = 0
        self.late_chunks = 0
        self.sequence_gaps = 0
        self.time_gaps = 0

    def __len__(self) -> int:
        return len(self._chunks)

    def push(self, chunk: AudioChunk) -> bool:
        """Return False on backpressure/late input; never silently reorder."""
        if not isinstance(chunk, AudioChunk):
            raise TypeError("chunk must be an AudioChunk")
        if self._session_id is not None and chunk.session_id != self._session_id:
            raise ValueError("cannot mix sessions in one audio buffer")
        if self._last_sequence is not None and (
            chunk.sequence_id <= self._last_sequence
            or chunk.start_ms < self._last_end_ms
        ):
            self.dropped_chunks += 1
            self.late_chunks += 1
            return False

        if len(self._chunks) >= self.capacity_chunks:
            self.dropped_chunks += 1
            return False

        if self._last_sequence is not None:
            self.sequence_gaps += chunk.sequence_id - self._last_sequence - 1
            if chunk.start_ms > self._last_end_ms:
                self.time_gaps += 1
        self._session_id = chunk.session_id
        self._last_sequence = chunk.sequence_id
        self._last_end_ms = chunk.start_ms + chunk.duration_ms
        self._chunks.append(chunk)
        return True

    def drain(self) -> list[AudioChunk]:
        chunks = list(self._chunks)
        self._chunks.clear()
        return chunks

    def release(self) -> None:
        """Clear audio and ordering state when capture stops."""
        self._chunks.clear()
        self._session_id = None
        self._last_sequence = None
        self._last_end_ms = None
