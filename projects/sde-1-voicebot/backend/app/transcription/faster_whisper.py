"""Local speech-to-text adapter using faster-whisper with automatic mock fallback."""

import io
import math
import os
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from app.contracts.audio import AudioChunk
from app.contracts.common import ErrorEnvelope
from app.contracts.transcription import TranscriptEvent, TranscriptSegment
from app.transcription.config import TranscriptionConfig
from app.transcription.mock import FakeTranscriber


class FasterWhisperAdapter:
    """Local faster-whisper adapter implementing TranscriptionAdapter.

    - Imports faster-whisper lazily so the default install runs without the stt extra.
    - Model size from config (default 'base'), CUDA when available, otherwise
      CPU 'int8'.
    - On model load, quota, or network failure, falls back to FakeTranscriber with a
      normalized ErrorEnvelope so the session continues cleanly.
    - Supports injected model instances for deterministic, mock-free unit tests.
    """

    def __init__(
        self,
        *,
        config: TranscriptionConfig | None = None,
        model: Any | None = None,
        fallback_transcriber: FakeTranscriber | None = None,
    ) -> None:
        self.config = config if config is not None else TranscriptionConfig.from_env()
        self._model = model
        self._fallback_transcriber = (
            fallback_transcriber
            if fallback_transcriber is not None
            else FakeTranscriber()
        )
        self._cancelled_sessions: set[str] = set()
        self._fallback_announced: set[str] = set()
        self._load_error: str | None = None
        self._segment_indices: dict[str, int] = {}
        self._error_counter: int = 0

    def _ensure_model_loaded(self) -> Any:
        """Lazily load the faster-whisper WhisperModel if not already provided."""
        if self._model is not None:
            return self._model

        if self._load_error is not None:
            raise RuntimeError(self._load_error)

        try:
            from faster_whisper import WhisperModel
        except ImportError as err:
            self._load_error = f"faster-whisper is not installed: {err}"
            raise RuntimeError(self._load_error) from err

        device, compute_type = self.config.resolve_device_and_compute()

        if os.getenv("STT_USE_SYSTEM_CERTS") == "1":
            try:
                import truststore

                truststore.inject_into_ssl()
            except Exception:
                pass

        try:
            self._model = WhisperModel(
                self.config.model_size,
                device=device,
                compute_type=compute_type,
            )
            return self._model
        except Exception as exc:
            self._load_error = f"Failed to load WhisperModel: {exc}"
            raise RuntimeError(self._load_error) from exc

    def health(self) -> str:
        """Return provider health status."""
        if self._load_error is not None:
            return "degraded"
        return "ready"

    def cancel(self, session_id: str) -> None:
        """Cancel in-flight transcription for a session."""
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a nonempty string")
        self._cancelled_sessions.add(session_id)
        self._fallback_announced.discard(session_id)
        self._fallback_transcriber.cancel(session_id)

    def reset(self, session_id: str | None = None) -> None:
        """Clear cancellations; segment and event IDs keep counting to stay unique."""
        if session_id:
            self._cancelled_sessions.discard(session_id)
            self._fallback_announced.discard(session_id)
        else:
            self._cancelled_sessions.clear()
            self._fallback_announced.clear()
        if hasattr(self._fallback_transcriber, "reset"):
            self._fallback_transcriber.reset(session_id)

    def transcribe(
        self,
        chunks: Sequence[AudioChunk],
        *,
        session_id: str,
        correlation_id: str,
        timestamp: datetime,
    ) -> list[TranscriptEvent]:
        """Transcribe audio chunks into timestamped transcript events."""
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a nonempty string")
        if not isinstance(correlation_id, str) or not correlation_id.strip():
            raise ValueError("correlation_id must be a nonempty string")
        if (
            not isinstance(timestamp, datetime)
            or timestamp.tzinfo is None
            or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp)
        ):
            raise ValueError("timestamp must be timezone-aware UTC")

        if session_id in self._cancelled_sessions:
            return []

        if not chunks:
            return []

        # Validate chunks consistency and ordering
        expected_seq = chunks[0].sequence_id
        prev_start = -1
        for chunk in chunks:
            if chunk.session_id != session_id:
                self._error_counter += 1
                error_payload = ErrorEnvelope(
                    code="TRANSCRIPTION_MIXED_SESSION",
                    message_safe_for_user=(
                        "Audio chunks belong to mixed or mismatched sessions."
                    ),
                    retryable=False,
                    correlation_id=correlation_id,
                    details_redacted={
                        "expected_session": session_id,
                        "received_session": chunk.session_id,
                    },
                )
                return [
                    TranscriptEvent(
                        event_id=f"evt-stt-err-{session_id}-{self._error_counter}",
                        event_type="transcript.error",
                        schema_version="1.0",
                        session_id=session_id,
                        correlation_id=correlation_id,
                        timestamp=timestamp,
                        producer="transcription",
                        payload=error_payload,
                    )
                ]

            if chunk.sequence_id < expected_seq or chunk.start_ms < prev_start:
                self._error_counter += 1
                error_payload = ErrorEnvelope(
                    code="TRANSCRIPTION_INVALID_ORDERING",
                    message_safe_for_user="Audio chunks are out of order.",
                    retryable=False,
                    correlation_id=correlation_id,
                    details_redacted={
                        "sequence_id": str(chunk.sequence_id),
                        "start_ms": str(chunk.start_ms),
                    },
                )
                return [
                    TranscriptEvent(
                        event_id=f"evt-stt-err-{session_id}-{self._error_counter}",
                        event_type="transcript.error",
                        schema_version="1.0",
                        session_id=session_id,
                        correlation_id=correlation_id,
                        timestamp=timestamp,
                        producer="transcription",
                        payload=error_payload,
                    )
                ]

            if chunk.sequence_id > expected_seq + 1:
                self._error_counter += 1
                error_payload = ErrorEnvelope(
                    code="TRANSCRIPTION_MISSING_CHUNKS",
                    message_safe_for_user="Detected missing audio chunks in stream.",
                    retryable=False,
                    correlation_id=correlation_id,
                    details_redacted={
                        "expected_sequence": str(expected_seq + 1),
                        "received_sequence": str(chunk.sequence_id),
                    },
                )
                return [
                    TranscriptEvent(
                        event_id=f"evt-stt-err-{session_id}-{self._error_counter}",
                        event_type="transcript.error",
                        schema_version="1.0",
                        session_id=session_id,
                        correlation_id=correlation_id,
                        timestamp=timestamp,
                        producer="transcription",
                        payload=error_payload,
                    )
                ]

            expected_seq = chunk.sequence_id
            prev_start = chunk.start_ms

        try:
            model = self._ensure_model_loaded()
            return self._transcribe_with_model(
                model,
                chunks,
                session_id=session_id,
                correlation_id=correlation_id,
                timestamp=timestamp,
            )
        except Exception as exc:
            self._error_counter += 1
            if not self.config.fallback_to_mock:
                # If fallback disabled, emit a normalized error event
                err_env = ErrorEnvelope(
                    code="TRANSCRIPTION_PROVIDER_ERROR",
                    message_safe_for_user="Local transcription model failed.",
                    retryable=False,
                    correlation_id=correlation_id,
                    details_redacted={
                        "reason": type(exc).__name__,
                        "provider": "faster_whisper",
                    },
                )
                return [
                    TranscriptEvent(
                        event_id=f"evt-err-{session_id}-{self._error_counter}",
                        event_type="transcript.error",
                        schema_version="1.0",
                        session_id=session_id,
                        correlation_id=correlation_id,
                        timestamp=timestamp,
                        producer="transcription",
                        payload=err_env,
                    )
                ]

            # Fall back to mock provider with an explicit, normalized ErrorEnvelope
            fallback_err = ErrorEnvelope(
                code="TRANSCRIPTION_FALLBACK_TO_MOCK",
                message_safe_for_user=(
                    "Local STT provider unavailable; fell back to mock provider."
                ),
                retryable=False,
                correlation_id=correlation_id,
                details_redacted={
                    "reason": type(exc).__name__,
                    "provider": "faster_whisper",
                },
            )
            fallback_event = TranscriptEvent(
                event_id=f"evt-fallback-{session_id}-{self._error_counter}",
                event_type="transcript.error",
                schema_version="1.0",
                session_id=session_id,
                correlation_id=correlation_id,
                timestamp=timestamp,
                producer="transcription",
                payload=fallback_err,
            )
            mock_events = self._fallback_transcriber.transcribe(
                chunks,
                session_id=session_id,
                correlation_id=correlation_id,
                timestamp=timestamp,
            )
            if session_id not in self._fallback_announced:
                self._fallback_announced.add(session_id)
                return [fallback_event, *mock_events]
            return list(mock_events)

    def _prepare_audio_input(self, raw_pcm: bytes) -> Any:
        """Prepare audio input for Whisper: normalized float32 array or WAV buffer."""
        try:
            import numpy as np

            return np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0
        except ImportError:
            # Fallback to in-memory RIFF/WAVE container with valid headers
            import wave

            wav_buf = io.BytesIO()
            with wave.open(wav_buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(raw_pcm)
            wav_buf.seek(0)
            return wav_buf

    def _transcribe_with_model(
        self,
        model: Any,
        chunks: Sequence[AudioChunk],
        *,
        session_id: str,
        correlation_id: str,
        timestamp: datetime,
    ) -> list[TranscriptEvent]:
        """Run speech recognition on the assembled PCM chunks."""
        # Check cancellation before heavy inference
        if session_id in self._cancelled_sessions:
            return []

        # Combine PCM bytes from chunks
        raw_pcm = b"".join(c.pcm for c in chunks)
        stream_base_ms = chunks[0].start_ms
        audio_data = self._prepare_audio_input(raw_pcm)

        segments_iterable, _ = model.transcribe(
            audio_data,
            language=self.config.language,
        )

        events: list[TranscriptEvent] = []
        seq_idx = self._segment_indices.get(session_id, 0)

        for seg in segments_iterable:
            if session_id in self._cancelled_sessions:
                return []

            text = seg.text.strip() if hasattr(seg, "text") else ""
            if not text:
                continue

            # Confidence calculation
            confidence = 1.0
            if hasattr(seg, "confidence") and seg.confidence is not None:
                confidence = float(seg.confidence)
            elif hasattr(seg, "avg_logprob") and seg.avg_logprob is not None:
                try:
                    confidence = max(0.0, min(1.0, math.exp(float(seg.avg_logprob))))
                except (OverflowError, ValueError):
                    confidence = 0.5

            start_s = float(getattr(seg, "start", 0.0))
            end_s = float(getattr(seg, "end", max(start_s, 0.02)))
            start_ms = stream_base_ms + int(start_s * 1000)
            end_ms = max(start_ms, stream_base_ms + int(end_s * 1000))

            segment_payload = TranscriptSegment(
                segment_id=f"{session_id}-fw-{seq_idx}",
                session_id=session_id,
                sequence_id=seq_idx,
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                confidence=confidence,
                language=self.config.language,
                is_final=True,
            )

            evt = TranscriptEvent(
                event_id=f"evt-{session_id}-fw-{seq_idx}",
                event_type="transcript.segment",
                schema_version="1.0",
                session_id=session_id,
                correlation_id=correlation_id,
                timestamp=timestamp,
                producer="transcription",
                payload=segment_payload,
            )
            events.append(evt)
            seq_idx += 1

        self._segment_indices[session_id] = seq_idx
        return events
