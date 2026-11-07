"""Week 2 mock device, capture lifecycle, buffer, VAD and W2 handoff."""

from datetime import datetime, timezone

import pytest

from app.audio.buffer import BoundedAudioBuffer
from app.audio.device import AudioDeviceError, MockAudioDevice, PermissionState
from app.audio.lifecycle import AudioCaptureController, CaptureState
from app.audio.vad import MockVAD, SpeechSpan
from app.contracts.audio import AudioChunk, AudioFormat
from app.transcription.mock import FakeTranscriber


def chunk(sequence: int, start: int, value: int = 10000) -> AudioChunk:
    return AudioChunk(
        session_id="session-1",
        sequence_id=sequence,
        start_ms=start,
        duration_ms=20,
        format=AudioFormat(),
        pcm=value.to_bytes(2, "little", signed=True) * 320,
    )


def controller(
    *, capacity: int = 4, allow_permission: bool = True
) -> AudioCaptureController:
    return AudioCaptureController(
        session_id="session-1",
        device=MockAudioDevice(allow_permission=allow_permission),
        buffer=BoundedAudioBuffer(capacity_chunks=capacity),
    )


def test_mock_device_permission_and_selection_without_real_capture() -> None:
    device = MockAudioDevice()
    assert device.permission is PermissionState.prompt
    assert device.list_devices() == ("mock:microphone",)
    with pytest.raises(AudioDeviceError) as error:
        device.read_chunks(session_id="session-1", duration_ms=20)
    assert error.value.code == "AUDIO_DEVICE_NOT_READY"
    assert device.request_permission("mock:microphone") is PermissionState.granted
    device.select_device("mock:microphone")
    first = device.read_chunks(session_id="session-1", duration_ms=40)
    assert first == device.read_chunks(session_id="session-1", duration_ms=40)
    assert [item.sequence_id for item in first] == [0, 1]


def test_denied_and_unsupported_device_errors_are_safe() -> None:
    denied = controller(allow_permission=False)
    with pytest.raises(AudioDeviceError) as error:
        denied.start("mock:microphone")
    assert error.value.code == "AUDIO_PERMISSION_DENIED"
    assert denied.state is CaptureState.created
    assert denied.device.permission is PermissionState.denied

    unavailable = MockAudioDevice(available=False)
    with pytest.raises(AudioDeviceError) as error:
        unavailable.request_permission("mock:microphone")
    assert error.value.code == "AUDIO_DEVICE_UNAVAILABLE"
    assert unavailable.list_devices() == ()

    with pytest.raises(AudioDeviceError) as error:
        controller().start("real:microphone")
    assert error.value.code == "AUDIO_DEVICE_UNAVAILABLE"


def test_audio_lifecycle_pause_resume_stop_and_offsets() -> None:
    capture = controller(capacity=5)
    with pytest.raises(ValueError):
        capture.pause()
    capture.start("mock:microphone")
    with pytest.raises(ValueError):
        capture.start("mock:microphone")
    assert capture.produce(duration_ms=40) == 2
    capture.pause()
    with pytest.raises(ValueError):
        capture.produce(duration_ms=20)
    capture.resume()
    assert capture.produce(duration_ms=20) == 1
    chunks = capture.buffer.drain()
    assert [(c.sequence_id, c.start_ms) for c in chunks] == [(0, 0), (1, 20), (2, 40)]
    capture.produce(duration_ms=20)
    capture.stop()
    assert capture.state is CaptureState.stopped
    assert len(capture.buffer) == 0
    with pytest.raises(ValueError):
        capture.resume()
    with pytest.raises(ValueError):
        capture.stop()


def test_buffer_overflow_backpressure_gaps_and_late_chunk() -> None:
    buffer = BoundedAudioBuffer(capacity_chunks=2)
    assert buffer.push(chunk(0, 0))
    assert buffer.push(chunk(1, 20))
    assert not buffer.push(chunk(2, 40))
    assert buffer.dropped_chunks == 1
    assert [c.sequence_id for c in buffer.drain()] == [0, 1]
    assert buffer.push(chunk(4, 80))
    assert buffer.sequence_gaps == 2  # 2 was dropped and 3 has not arrived
    assert buffer.time_gaps == 1
    assert not buffer.push(chunk(3, 60))
    assert buffer.late_chunks == 1
    assert buffer.dropped_chunks == 2
    assert [c.sequence_id for c in buffer.drain()] == [4]
    with pytest.raises(ValueError):
        buffer.push(chunk(5, 100).model_copy(update={"session_id": "other"}))
    buffer.release()
    assert len(buffer) == 0
    assert buffer.push(chunk(0, 0))


def test_chunk_rejected_when_full_can_be_retried_after_drain() -> None:
    buffer = BoundedAudioBuffer(capacity_chunks=1)
    assert buffer.push(chunk(0, 0))
    assert not buffer.push(chunk(1, 20))
    assert buffer.dropped_chunks == 1
    assert [c.sequence_id for c in buffer.drain()] == [0]

    assert buffer.push(chunk(1, 20))
    assert buffer.late_chunks == 0
    assert buffer.sequence_gaps == 0
    assert buffer.time_gaps == 0
    assert [c.sequence_id for c in buffer.drain()] == [1]


def test_gap_is_not_counted_for_a_rejected_chunk() -> None:
    buffer = BoundedAudioBuffer(capacity_chunks=1)
    assert buffer.push(chunk(0, 0))
    assert not buffer.push(chunk(5, 100))
    assert buffer.sequence_gaps == 0
    assert buffer.time_gaps == 0


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5])
def test_invalid_buffer_capacity_rejected(capacity: object) -> None:
    with pytest.raises(ValueError):
        BoundedAudioBuffer(capacity_chunks=capacity)


def test_vad_threshold_minimum_duration_noise_and_gap() -> None:
    speech = [chunk(0, 0), chunk(1, 20), chunk(2, 40)]
    noise = chunk(3, 60, value=100)
    vad = MockVAD(threshold=0.2, min_speech_ms=40)
    assert vad.detect([speech[0]]) == []
    assert vad.detect(speech + [noise]) == [SpeechSpan("session-1", 0, 60)]
    assert vad.detect(speech + [noise]) == vad.detect(speech + [noise])
    assert MockVAD(threshold=0.5, min_speech_ms=20).detect(speech) == []
    assert vad.detect([speech[0], chunk(2, 40)]) == []


def test_vad_rejects_bad_order_and_mixed_sessions() -> None:
    vad = MockVAD()
    with pytest.raises(ValueError):
        vad.detect([chunk(1, 20), chunk(0, 0)])
    with pytest.raises(ValueError):
        vad.detect(
            [chunk(0, 0), chunk(1, 20).model_copy(update={"session_id": "other"})]
        )


@pytest.mark.parametrize(
    ("threshold", "minimum"),
    [
        (float("nan"), 20),
        (float("inf"), 20),
        (-0.1, 20),
        (1.1, 20),
        (True, 20),
        (0.1, 0),
        (0.1, True),
    ],
)
def test_invalid_vad_configuration_rejected(threshold: object, minimum: object) -> None:
    with pytest.raises(ValueError):
        MockVAD(threshold=threshold, min_speech_ms=minimum)


def test_w1_week2_chunks_feed_real_w2_fake_transcriber() -> None:
    capture = controller(capacity=5)
    capture.start("mock:microphone")
    capture.produce(duration_ms=60, chunk_ms=20)
    chunks = capture.buffer.drain()
    events = FakeTranscriber().transcribe(
        chunks,
        session_id="session-1",
        correlation_id="correlation-1",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert len(events) == 1
    assert events[0].event_type == "transcript.segment"
    assert events[0].payload.end_ms == 60
