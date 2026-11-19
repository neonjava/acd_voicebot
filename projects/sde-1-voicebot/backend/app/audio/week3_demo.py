"""Week 3 audio demo: wake gate, speech events, device-loss recovery, W2 handoff."""

import argparse
from datetime import datetime, timezone

from app.audio.buffer import BoundedAudioBuffer
from app.audio.chunker import chunk_pcm
from app.audio.config import (
    AudioConfig,
    create_audio_device,
    create_wake_word_detector,
)
from app.audio.device import AudioDeviceError, MockAudioDevice, SoundDeviceMicrophone
from app.audio.lifecycle import AudioCaptureController
from app.audio.pipeline import SpeechPipeline, to_speech_envelope
from app.audio.source import make_fake_pcm
from app.audio.wake import make_wake_pcm
from app.contracts.audio import AudioChunk, AudioFormat
from app.transcription.orchestrator import TranscriptionOrchestrator


def _build_mock_stream(session_id: str) -> list[AudioChunk]:
    """Build deterministic silence -> wake -> speech -> silence -> post-end chunks."""
    silence = bytes(640)
    speech_pcm = make_fake_pcm(duration_ms=60)
    wake_pcm = make_wake_pcm(duration_ms=20, above_threshold=True)

    raw_chunks = [
        AudioChunk(
            session_id=session_id,
            sequence_id=0,
            start_ms=0,
            duration_ms=20,
            format=AudioFormat(),
            pcm=silence,
        ),
        AudioChunk(
            session_id=session_id,
            sequence_id=1,
            start_ms=20,
            duration_ms=20,
            format=AudioFormat(),
            pcm=wake_pcm,
        ),
        *[
            AudioChunk(
                session_id=session_id,
                sequence_id=2 + idx,
                start_ms=40 + idx * 20,
                duration_ms=20,
                format=AudioFormat(),
                pcm=c.pcm,
            )
            for idx, c in enumerate(
                chunk_pcm(speech_pcm, session_id=session_id, chunk_ms=20)
            )
        ],
        AudioChunk(
            session_id=session_id,
            sequence_id=5,
            start_ms=100,
            duration_ms=20,
            format=AudioFormat(),
            pcm=silence,
        ),
    ]
    return raw_chunks


def run_mock_demo() -> int:
    """Run deterministic mock wake -> speech -> W2 handoff and recovery demo."""
    session_id = "session-demo"
    correlation_id = "correlation-demo"
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    config = AudioConfig()
    orchestrator = TranscriptionOrchestrator()
    pipeline = SpeechPipeline(
        session_id=session_id,
        correlation_id=correlation_id,
        config=config,
        orchestrator=orchestrator,
    )

    chunks = _build_mock_stream(session_id)
    result = pipeline.process_chunks(chunks, timestamp=timestamp, final=True)
    for event in result.speech_events:
        envelope = to_speech_envelope(
            event,
            event_id=f"event-audio-{event.sequence_id}",
            timestamp=timestamp,
        )
        print(
            f"speech_event seq={event.sequence_id} kind={event.kind} "
            f"at_ms={event.at_ms} envelope_type={envelope.event_type} "
            f"session_id={event.session_id} correlation_id={event.correlation_id}"
            + (
                f" wake_word={event.wake_word} score={event.score:.2f}"
                if event.kind == "wake"
                else ""
            )
        )

    print(
        f"handoff_chunks={len(result.utterance_chunks)} "
        f"transcript_events={len(result.transcript_events)} "
        f"transcript_text={orchestrator.get_transcript_text()!r}"
    )

    # Demonstrate transient device loss and bounded reconnect without reusing IDs.
    device = MockAudioDevice()
    buffer = BoundedAudioBuffer(capacity_chunks=8)
    capture = AudioCaptureController(
        session_id=session_id,
        correlation_id=correlation_id,
        device=device,
        buffer=buffer,
        reconnect_backoff_ms=0,
    )
    capture.start(MockAudioDevice.DEVICE_ID)
    capture.produce(duration_ms=40, chunk_ms=20)
    device.disconnect(failures_before_recover=1)
    capture.produce(duration_ms=40, chunk_ms=20)
    drained = buffer.drain()
    print(
        f"recovery reconnects={capture.reconnect_count} "
        f"sequence_ids={[c.sequence_id for c in drained]}"
    )
    capture.cancel()
    print(f"cancelled={capture.cancelled} buffered_after_cancel={len(buffer)}")
    return 0


def run_mic_demo(
    *, duration_ms: int = 5000, chunk_ms: int = 20, config: AudioConfig | None = None
) -> int:
    """Run live capture using SoundDeviceMicrophone and OpenWakeWordDetector."""
    base = config if config is not None else AudioConfig.from_env()
    config = base.model_copy(update={"audio_source": "mic"})
    device = create_audio_device(config)
    detector = create_wake_word_detector(config)
    buffer = BoundedAudioBuffer(capacity_chunks=512)
    session_id = "session-mic-demo"
    correlation_id = "correlation-mic-demo"
    capture = AudioCaptureController.from_config(
        config,
        session_id=session_id,
        correlation_id=correlation_id,
        device=device,
        buffer=buffer,
    )
    orchestrator = TranscriptionOrchestrator()
    pipeline = SpeechPipeline(
        session_id=session_id,
        correlation_id=correlation_id,
        config=config,
        wake_detector=detector,
        orchestrator=orchestrator,
    )
    device_id = SoundDeviceMicrophone.DEVICE_ID
    try:
        capture.start(device_id)
        print(
            f"listening on the default microphone for {duration_ms} ms; "
            "say 'hey jarvis' and then a short sentence"
        )
        steps = max(1, duration_ms // chunk_ms)
        for _ in range(steps):
            capture.produce(duration_ms=chunk_ms, chunk_ms=chunk_ms)
            for chunk in buffer.drain():
                step = pipeline.process_chunk(
                    chunk, timestamp=datetime.now(timezone.utc)
                )
                for evt in step.speech_events:
                    print(
                        f"speech_event seq={evt.sequence_id} kind={evt.kind} "
                        f"at_ms={evt.at_ms}"
                    )
        flushed = pipeline.flush(timestamp=datetime.now(timezone.utc))
        for evt in flushed.speech_events:
            print(
                f"speech_event seq={evt.sequence_id} kind={evt.kind} at_ms={evt.at_ms}"
            )
    except AudioDeviceError as exc:
        print(f"audio_error code={exc.code} message={exc}")
        return 2
    finally:
        capture.cancel()
    kinds = [evt.kind for evt in pipeline.events]
    print(
        f"done: wakes={kinds.count('wake')} utterances={kinds.count('speech_end')} "
        f"transcript_events={len(pipeline.transcript_events)}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    env_config = AudioConfig.from_env()
    parser = argparse.ArgumentParser(description="Week 3 audio speech-events demo")
    parser.add_argument(
        "--source",
        choices=("mock", "mic"),
        default=env_config.audio_source,
        help="defaults to AUDIO_SOURCE (mock when unset)",
    )
    parser.add_argument("--duration-ms", type=int, default=5000)
    args = parser.parse_args(argv)
    if args.source == "mic":
        return run_mic_demo(duration_ms=args.duration_ms, config=env_config)
    return run_mock_demo()


if __name__ == "__main__":
    raise SystemExit(main())
