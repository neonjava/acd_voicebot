"""Show Week 2 mock capture, VAD and backpressure without real devices."""

from app.audio.buffer import BoundedAudioBuffer
from app.audio.device import MockAudioDevice
from app.audio.lifecycle import AudioCaptureController
from app.audio.vad import MockVAD


def main() -> None:
    device = MockAudioDevice()
    buffer = BoundedAudioBuffer(capacity_chunks=3)
    capture = AudioCaptureController(
        session_id="session-demo", device=device, buffer=buffer
    )
    capture.start(MockAudioDevice.DEVICE_ID)
    capture.produce(duration_ms=40, chunk_ms=20)
    capture.pause()
    capture.resume()
    capture.produce(duration_ms=40, chunk_ms=20)
    chunks = buffer.drain()
    speech = MockVAD(threshold=0.1, min_speech_ms=40).detect(chunks)
    print(
        f"state={capture.state.value} retained={len(chunks)} "
        f"dropped={buffer.dropped_chunks} "
        f"speech_spans={[(span.start_ms, span.end_ms) for span in speech]}"
    )
    capture.stop()
    print(f"state={capture.state.value} buffered={len(buffer)}")


if __name__ == "__main__":
    main()
