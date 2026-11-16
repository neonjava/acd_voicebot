"""Week 3 audio tests: speech events, wake gate, recovery, lazy extras, W2 handoff."""

import subprocess
import sys
import types
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.audio.buffer import BoundedAudioBuffer
from app.audio.config import (
    AudioConfig,
    create_audio_device,
    create_vad,
    create_wake_word_detector,
)
from app.audio.device import (
    AudioDeviceError,
    MockAudioDevice,
    PermissionState,
    SoundDeviceMicrophone,
)
from app.audio.lifecycle import AudioCaptureController, CaptureState
from app.audio.pipeline import (
    SpeechPipeline,
    spans_to_speech_events,
    to_speech_envelope,
)
from app.audio.source import make_fake_pcm
from app.audio.vad import MockVAD, SileroVAD, SpeechSpan
from app.audio.wake import (
    MockWakeWordDetector,
    OpenWakeWordDetector,
    make_wake_pcm,
)
from app.audio.week3_demo import main as demo_main
from app.contracts.audio import AudioChunk, AudioError, AudioFormat
from app.transcription.orchestrator import TranscriptionOrchestrator

FIXED_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)
SESSION_ID = "session-w3"
CORRELATION_ID = "correlation-w3"


def make_chunk(
    seq: int,
    start_ms: int,
    *,
    pcm: bytes | None = None,
    sample_value: int = 10000,
    duration_ms: int = 20,
    session_id: str = SESSION_ID,
) -> AudioChunk:
    if pcm is None:
        samples = duration_ms * 16
        pcm = sample_value.to_bytes(2, "little", signed=True) * samples
    return AudioChunk(
        session_id=session_id,
        sequence_id=seq,
        start_ms=start_ms,
        duration_ms=duration_ms,
        format=AudioFormat(),
        pcm=pcm,
    )


def silence_chunk(seq: int, start_ms: int, duration_ms: int = 20) -> AudioChunk:
    return make_chunk(
        seq, start_ms, pcm=bytes(duration_ms * 32), duration_ms=duration_ms
    )


def wake_chunk(
    seq: int, start_ms: int, *, above_threshold: bool = True, duration_ms: int = 20
) -> AudioChunk:
    return make_chunk(
        seq,
        start_ms,
        pcm=make_wake_pcm(duration_ms=duration_ms, above_threshold=above_threshold),
        duration_ms=duration_ms,
    )


def build_pipeline(
    *,
    wake_required: bool = True,
    wake_threshold: float = 0.5,
    silence_timeout_ms: int = 2000,
    speech_end_silence_ms: int = 20,
    with_orchestrator: bool = True,
    wake_detector: MockWakeWordDetector | None = None,
) -> tuple[SpeechPipeline, TranscriptionOrchestrator | None]:
    cfg = AudioConfig(
        wake_required=wake_required,
        wake_threshold=wake_threshold,
        silence_timeout_ms=silence_timeout_ms,
        # Fixtures use one 20 ms silent chunk to end speech; the real default
        # (400 ms) is covered by the hangover tests below.
        speech_end_silence_ms=speech_end_silence_ms,
        vad_threshold=0.1,
        vad_min_speech_ms=40,
    )
    orch = TranscriptionOrchestrator() if with_orchestrator else None
    pipeline = SpeechPipeline(
        session_id=SESSION_ID,
        correlation_id=CORRELATION_ID,
        config=cfg,
        wake_detector=wake_detector,
        orchestrator=orch,
    )
    return pipeline, orch


def test_speech_events_order_ids_and_envelope() -> None:
    pipeline, orch = build_pipeline(wake_required=True)
    assert orch is not None
    chunks = [
        wake_chunk(0, 0),
        make_chunk(1, 20),
        make_chunk(2, 40),
        make_chunk(3, 60),
        silence_chunk(4, 80),
    ]
    result = pipeline.process_chunks(chunks, timestamp=FIXED_TS)

    assert [e.kind for e in result.speech_events] == [
        "wake",
        "speech_start",
        "speech_end",
    ]
    assert [e.sequence_id for e in result.speech_events] == [0, 1, 2]
    assert [e.at_ms for e in result.speech_events] == [0, 20, 80]
    assert all(e.session_id == SESSION_ID for e in result.speech_events)
    assert all(e.correlation_id == CORRELATION_ID for e in result.speech_events)
    assert result.speech_events[0].wake_word == "hey_jarvis"
    assert result.speech_events[0].score == pytest.approx(0.95)
    assert result.speech_events[1].wake_word is None
    assert result.speech_events[2].score is None

    envelopes = [
        to_speech_envelope(evt, event_id=f"evt-{evt.sequence_id}", timestamp=FIXED_TS)
        for evt in result.speech_events
    ]
    assert all(env.event_type == "audio.speech" for env in envelopes)
    assert all(env.producer == "audio" for env in envelopes)
    assert [env.payload.kind for env in envelopes] == [
        "wake",
        "speech_start",
        "speech_end",
    ]

    assert [c.sequence_id for c in result.utterance_chunks] == [1, 2, 3]
    segments = orch.get_segments()
    assert len(segments) == 1
    assert segments[0].start_ms == 20
    assert segments[0].end_ms == 80
    assert segments[0].text == "Hello from the mock voicebot."


def test_spans_to_speech_events_converts_multiple_spans_and_rejects_mismatch() -> None:
    spans = [
        SpeechSpan(SESSION_ID, 20, 80),
        SpeechSpan(SESSION_ID, 140, 200),
    ]
    events = spans_to_speech_events(
        spans, session_id=SESSION_ID, correlation_id=CORRELATION_ID, start_sequence_id=1
    )
    assert [(e.kind, e.sequence_id, e.at_ms) for e in events] == [
        ("speech_start", 1, 20),
        ("speech_end", 2, 80),
        ("speech_start", 3, 140),
        ("speech_end", 4, 200),
    ]
    with pytest.raises(ValueError, match="session_id"):
        spans_to_speech_events(
            [SpeechSpan("other-session", 0, 40)],
            session_id=SESSION_ID,
            correlation_id=CORRELATION_ID,
        )


def test_nothing_emitted_before_wake_and_listening_closes_after_speech_end() -> None:
    pipeline, orch = build_pipeline(wake_required=True)
    assert orch is not None

    pre_wake = [make_chunk(0, 0), make_chunk(1, 20), silence_chunk(2, 40)]
    before_result = pipeline.process_chunks(pre_wake, timestamp=FIXED_TS)
    assert before_result.speech_events == []
    assert before_result.utterance_chunks == []
    assert before_result.transcript_events == []
    assert orch.get_segments() == []
    assert pipeline.listening is False

    utterance = [
        wake_chunk(3, 60),
        make_chunk(4, 80),
        make_chunk(5, 100),
        silence_chunk(6, 120),
    ]
    after_result = pipeline.process_chunks(utterance, timestamp=FIXED_TS)
    assert [e.kind for e in after_result.speech_events] == [
        "wake",
        "speech_start",
        "speech_end",
    ]
    assert pipeline.listening is False

    # A follow-up utterance without a new wake word must be gated off.
    unwoken_followup = [make_chunk(7, 140), make_chunk(8, 160), silence_chunk(9, 180)]
    followup_result = pipeline.process_chunks(unwoken_followup, timestamp=FIXED_TS)
    assert followup_result.speech_events == []
    assert len(orch.get_segments()) == 1


def test_wake_listening_closes_after_configurable_silence_timeout() -> None:
    pipeline, orch = build_pipeline(wake_required=True, silence_timeout_ms=60)
    assert orch is not None

    wake_res = pipeline.process_chunk(wake_chunk(0, 0), timestamp=FIXED_TS)
    assert [e.kind for e in wake_res.speech_events] == ["wake"]
    assert pipeline.listening is True

    # 40 ms of silence: still open (< 60 ms timeout).
    pipeline.process_chunks(
        [silence_chunk(1, 20), silence_chunk(2, 40)], timestamp=FIXED_TS
    )
    assert pipeline.listening is True

    # 60 ms of silence reached: listening closes.
    pipeline.process_chunk(silence_chunk(3, 60), timestamp=FIXED_TS)
    assert pipeline.listening is False
    assert pipeline.silence_timeouts == 1

    # Speech arriving after timeout emits nothing.
    late_speech = pipeline.process_chunks(
        [make_chunk(4, 80), make_chunk(5, 100), silence_chunk(6, 120)],
        timestamp=FIXED_TS,
    )
    assert late_speech.speech_events == []
    assert orch.get_segments() == []


def test_below_threshold_wake_score_emits_nothing() -> None:
    detector = MockWakeWordDetector(threshold=0.5, score_by_sequence={1: 0.49})
    pipeline, orch = build_pipeline(wake_required=True, wake_detector=detector)
    assert orch is not None

    chunks = [
        wake_chunk(0, 0, above_threshold=False),  # deterministic score 0.3 < 0.5
        make_chunk(1, 20),  # overridden score 0.49 < 0.5
        make_chunk(2, 40),
        make_chunk(3, 60),
        silence_chunk(4, 80),
    ]
    result = pipeline.process_chunks(chunks, timestamp=FIXED_TS)
    assert result.speech_events == []
    assert result.utterance_chunks == []
    assert result.transcript_events == []
    assert pipeline.listening is False
    assert orch.get_segments() == []


@pytest.mark.parametrize("wake_required", [True, False])
def test_silence_emits_nothing(wake_required: bool) -> None:
    pipeline, orch = build_pipeline(wake_required=wake_required)
    assert orch is not None

    silence = [silence_chunk(i, i * 20) for i in range(10)]
    result = pipeline.process_chunks(silence, timestamp=FIXED_TS, final=True)
    assert result.speech_events == []
    assert result.utterance_chunks == []
    assert result.transcript_events == []
    assert orch.get_segments() == []


@pytest.mark.parametrize("wake_required", [True, False])
def test_noise_only_audio_emits_no_speech_and_no_transcript(
    wake_required: bool,
) -> None:
    pipeline, orch = build_pipeline(wake_required=wake_required)
    assert orch is not None

    chunks: list[AudioChunk] = []
    seq = 0
    if wake_required:
        chunks.append(wake_chunk(seq, 0))
        seq += 1
    # Low-level noise (100/32768 = 0.003 < vad_threshold=0.1) plus a brief 20 ms pop.
    chunks.extend(
        [
            make_chunk(seq, seq * 20, sample_value=100),
            make_chunk(seq + 1, (seq + 1) * 20, sample_value=12000),  # 20 ms < 40 ms
            make_chunk(seq + 2, (seq + 2) * 20, sample_value=100),
            make_chunk(seq + 3, (seq + 3) * 20, sample_value=100),
        ]
    )
    result = pipeline.process_chunks(chunks, timestamp=FIXED_TS, final=True)
    assert [e for e in result.speech_events if e.kind != "wake"] == []
    assert result.utterance_chunks == []
    assert result.transcript_events == []
    assert orch.get_segments() == []


def test_sequence_gaps_split_speech_cleanly_and_preserve_w2_handoff() -> None:
    pipeline, orch = build_pipeline(wake_required=False)
    assert orch is not None

    # Gap between seq 1 (20..40) and seq 3 (60..80): splits into two valid utterances.
    chunks = [
        make_chunk(0, 0),
        make_chunk(1, 20),
        make_chunk(3, 60),
        make_chunk(4, 80),
        silence_chunk(5, 100),
    ]
    result = pipeline.process_chunks(chunks, timestamp=FIXED_TS)

    assert [(e.kind, e.sequence_id, e.at_ms) for e in result.speech_events] == [
        ("speech_start", 0, 0),
        ("speech_end", 1, 40),
        ("speech_start", 2, 60),
        ("speech_end", 3, 100),
    ]
    assert [c.sequence_id for c in result.utterance_chunks] == [0, 1, 3, 4]
    segments = orch.get_segments()
    assert [(s.start_ms, s.end_ms) for s in segments] == [(0, 40), (60, 100)]
    assert orch.get_gaps(min_gap_ms=1) == [(40, 60)]


def test_late_chunk_after_speech_end_is_dropped_and_not_transcribed() -> None:
    pipeline, orch = build_pipeline(wake_required=True)
    assert orch is not None

    chunks = [
        wake_chunk(0, 0),
        make_chunk(1, 20),
        make_chunk(2, 40),
        silence_chunk(3, 60),
    ]
    first = pipeline.process_chunks(chunks, timestamp=FIXED_TS)
    assert [e.kind for e in first.speech_events] == [
        "wake",
        "speech_start",
        "speech_end",
    ]
    assert len(orch.get_segments()) == 1

    # Out-of-order late chunk and overlapping-timestamp late chunk after speech_end.
    late_by_seq = pipeline.process_chunk(make_chunk(2, 80), timestamp=FIXED_TS)
    late_by_time = pipeline.process_chunk(make_chunk(4, 50), timestamp=FIXED_TS)
    in_order_post_end = pipeline.process_chunk(make_chunk(4, 80), timestamp=FIXED_TS)

    for res in (late_by_seq, late_by_time, in_order_post_end):
        assert res.speech_events == []
        assert res.utterance_chunks == []
        assert res.transcript_events == []
    assert pipeline.late_chunks == 2
    assert len(orch.get_segments()) == 1


def test_device_loss_mid_session_reconnects_without_reusing_sequence_ids() -> None:
    device = MockAudioDevice()
    buffer = BoundedAudioBuffer(capacity_chunks=8)
    slept: list[float] = []
    capture = AudioCaptureController(
        session_id=SESSION_ID,
        correlation_id=CORRELATION_ID,
        device=device,
        buffer=buffer,
        max_reconnect_attempts=3,
        reconnect_backoff_ms=50,
        sleep_fn=slept.append,
    )
    capture.start(MockAudioDevice.DEVICE_ID)
    assert capture.produce(duration_ms=40, chunk_ms=20) == 2

    device.disconnect(failures_before_recover=1)
    assert capture.produce(duration_ms=40, chunk_ms=20) == 2

    assert capture.reconnect_count == 1
    assert capture.reconnect_backoffs_ms == [50, 100]
    assert slept == [0.05, 0.1]
    assert capture.last_error is None

    drained = buffer.drain()
    assert [(c.sequence_id, c.start_ms) for c in drained] == [
        (0, 0),
        (1, 20),
        (2, 40),
        (3, 60),
    ]


def test_device_loss_reports_safe_audio_device_lost_after_all_attempts_fail() -> None:
    device = MockAudioDevice()
    buffer = BoundedAudioBuffer(capacity_chunks=8)
    slept: list[float] = []
    capture = AudioCaptureController(
        session_id=SESSION_ID,
        correlation_id=CORRELATION_ID,
        device=device,
        buffer=buffer,
        max_reconnect_attempts=3,
        reconnect_backoff_ms=25,
        sleep_fn=slept.append,
    )
    capture.start(MockAudioDevice.DEVICE_ID)
    capture.produce(duration_ms=20, chunk_ms=20)
    device.disconnect()  # Permanent loss

    with pytest.raises(AudioDeviceError) as exc_info:
        capture.produce(duration_ms=20, chunk_ms=20)

    assert exc_info.value.code == "AUDIO_DEVICE_LOST"
    assert capture.reconnect_count == 0
    assert capture.reconnect_backoffs_ms == [25, 50, 100]
    assert slept == [0.025, 0.05, 0.1]
    assert isinstance(capture.last_error, AudioError)
    assert capture.last_error.code == "AUDIO_DEVICE_LOST"
    assert capture.last_error.retryable is False
    assert capture.last_error.correlation_id == CORRELATION_ID
    assert capture.last_error.details_redacted == {"attempts": "3"}


def test_cancellation_stops_capture_and_releases_buffer() -> None:
    device = MockAudioDevice()
    buffer = BoundedAudioBuffer(capacity_chunks=8)
    capture = AudioCaptureController(
        session_id=SESSION_ID,
        correlation_id=CORRELATION_ID,
        device=device,
        buffer=buffer,
    )
    capture.start(MockAudioDevice.DEVICE_ID)
    capture.produce(duration_ms=40, chunk_ms=20)
    assert len(buffer) == 2

    capture.cancel()
    assert capture.cancelled is True
    assert capture.state is CaptureState.stopped
    assert len(buffer) == 0
    with pytest.raises(ValueError, match="active"):
        capture.produce(duration_ms=20, chunk_ms=20)

    # Cancellation during reconnect aborts remaining retries and releases buffer.
    device2 = MockAudioDevice()
    buffer2 = BoundedAudioBuffer(capacity_chunks=8)
    capture2 = AudioCaptureController(
        session_id=SESSION_ID,
        correlation_id=CORRELATION_ID,
        device=device2,
        buffer=buffer2,
        max_reconnect_attempts=3,
        reconnect_backoff_ms=20,
        sleep_fn=lambda _: capture2.cancel(),
    )
    capture2.start(MockAudioDevice.DEVICE_ID)
    capture2.produce(duration_ms=20, chunk_ms=20)
    device2.disconnect()
    with pytest.raises(AudioDeviceError) as exc_info:
        capture2.produce(duration_ms=20, chunk_ms=20)
    assert exc_info.value.code == "AUDIO_CAPTURE_CANCELLED"
    assert len(capture2.reconnect_backoffs_ms) == 1
    assert len(buffer2) == 0
    assert capture2.state is CaptureState.stopped


def test_pipeline_cancel_discards_pending_utterance_without_handoff() -> None:
    pipeline, orch = build_pipeline(wake_required=True)
    assert orch is not None
    pipeline.process_chunks([wake_chunk(0, 0), make_chunk(1, 20)], timestamp=FIXED_TS)
    pipeline.cancel()
    assert pipeline.cancelled is True
    assert pipeline.listening is False

    flushed = pipeline.flush(timestamp=FIXED_TS)
    assert flushed.speech_events == []
    assert flushed.utterance_chunks == []
    assert orch.get_segments() == []


def test_default_config_uses_mock_device_and_mock_wake() -> None:
    cfg = AudioConfig()
    assert cfg.audio_source == "mock"
    assert cfg.wake_required is True
    assert cfg.wake_threshold == 0.5
    assert cfg.wake_word == "hey_jarvis"

    device = create_audio_device(cfg)
    detector = create_wake_word_detector(cfg)
    assert isinstance(device, MockAudioDevice)
    assert isinstance(detector, MockWakeWordDetector)
    assert detector.threshold == 0.5

    env_cfg = AudioConfig.from_env()
    assert env_cfg.audio_source == "mock"
    assert isinstance(create_audio_device(env_cfg), MockAudioDevice)

    mic_cfg = AudioConfig(audio_source="mic", wake_threshold=0.65)
    mic_device = create_audio_device(mic_cfg)
    mic_detector = create_wake_word_detector(mic_cfg)
    assert isinstance(mic_device, SoundDeviceMicrophone)
    assert isinstance(mic_detector, OpenWakeWordDetector)
    assert mic_detector.threshold == 0.65

    with pytest.raises(ValidationError):
        AudioConfig(wake_threshold=True)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        AudioConfig(silence_timeout_ms=True)  # type: ignore[arg-type]


def test_app_audio_imports_without_audio_extra() -> None:
    script = (
        "import sys\n"
        "for mod in ('sounddevice', 'openwakeword', 'openwakeword.model', 'numpy'):\n"
        "    sys.modules[mod] = None\n"
        "import app.audio\n"
        "from app.audio import (\n"
        "    AudioConfig, AudioDeviceError, MockAudioDevice, MockVAD,\n"
        "    MockWakeWordDetector, OpenWakeWordDetector, SoundDeviceMicrophone,\n"
        "    SpeechPipeline,\n"
        ")\n"
        "cfg = AudioConfig()\n"
        "assert cfg.audio_source == 'mock'\n"
        "mic = SoundDeviceMicrophone()\n"
        "try:\n"
        "    mic.list_devices()\n"
        "    raise AssertionError('expected AudioDeviceError')\n"
        "except AudioDeviceError as exc:\n"
        "    assert exc.code == 'AUDIO_DEPENDENCY_MISSING'\n"
        "oww = OpenWakeWordDetector(threshold=0.5)\n"
        "assert oww.threshold == 0.5\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr

    oww = OpenWakeWordDetector(threshold=0.5)
    with pytest.raises(AudioDeviceError) as wake_err:
        oww.detect(make_chunk(0, 0))
    assert wake_err.value.code == "AUDIO_DEPENDENCY_MISSING"


def test_sounddevice_microphone_contract_and_device_loss_with_fake_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError):
        SoundDeviceMicrophone(sample_rate_hz=44100)
    with pytest.raises(ValidationError):
        SoundDeviceMicrophone(channels=2)

    pcm_payload = make_fake_pcm(duration_ms=40)
    stream_state = {"started": False, "closed": False, "fail_read": False}

    class FakeRawInputStream:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        def start(self) -> None:
            stream_state["started"] = True

        def read(self, frames: int) -> tuple[bytes, bool]:
            if stream_state["fail_read"]:
                raise OSError("usb microphone unplugged")
            assert frames == 640  # 40 ms * 16 samples/ms
            return pcm_payload, False

        def stop(self) -> None:
            pass

        def close(self) -> None:
            stream_state["closed"] = True

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.query_devices = lambda: [  # type: ignore[attr-defined]
        {"name": "Built-in Mic", "max_input_channels": 1}
    ]
    fake_sd.check_input_settings = lambda **kwargs: None  # type: ignore[attr-defined]
    fake_sd.RawInputStream = FakeRawInputStream  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    mic = SoundDeviceMicrophone()
    devices = mic.list_devices()
    assert SoundDeviceMicrophone.DEVICE_ID in devices
    permission = mic.request_permission(SoundDeviceMicrophone.DEVICE_ID)
    assert permission is PermissionState.granted
    mic.select_device(SoundDeviceMicrophone.DEVICE_ID)
    assert stream_state["started"] is True

    chunks = mic.read_chunks(session_id=SESSION_ID, duration_ms=40, chunk_ms=20)
    assert len(chunks) == 2
    assert chunks[0].format == AudioFormat(
        sample_rate_hz=16000, channels=1, encoding="pcm_s16le"
    )
    assert b"".join(c.pcm for c in chunks) == pcm_payload

    stream_state["fail_read"] = True
    with pytest.raises(AudioDeviceError) as err:
        mic.read_chunks(session_id=SESSION_ID, duration_ms=40, chunk_ms=20)
    assert err.value.code == "AUDIO_DEVICE_LOST"
    assert stream_state["closed"] is True


def test_openwakeword_detector_uses_onnx_and_config_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_models: list[dict[str, object]] = []
    scores = iter([0.49, 0.72])

    class FakeModel:
        def __init__(
            self, *, wakeword_models: list[str], inference_framework: str
        ) -> None:
            created_models.append(
                {
                    "wakeword_models": wakeword_models,
                    "inference_framework": inference_framework,
                }
            )

        def predict(self, _samples: object) -> dict[str, float]:
            return {"hey_jarvis": next(scores)}

    fake_oww = types.ModuleType("openwakeword")
    fake_oww_model = types.ModuleType("openwakeword.model")
    fake_oww_model.Model = FakeModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openwakeword", fake_oww)
    monkeypatch.setitem(sys.modules, "openwakeword.model", fake_oww_model)

    detector = OpenWakeWordDetector(threshold=0.5)
    assert detector.detect(make_chunk(0, 0)) is None
    hit = detector.detect(make_chunk(1, 20))
    assert hit is not None
    assert hit.wake_word == "hey_jarvis"
    assert hit.score == pytest.approx(0.72)
    assert hit.at_ms == 20
    assert created_models == [
        {"wakeword_models": ["hey_jarvis"], "inference_framework": "onnx"}
    ]


def test_end_to_end_capture_pipeline_to_real_w2_orchestrator() -> None:
    device = MockAudioDevice()
    buffer = BoundedAudioBuffer(capacity_chunks=16)
    capture = AudioCaptureController(
        session_id=SESSION_ID,
        correlation_id=CORRELATION_ID,
        device=device,
        buffer=buffer,
    )
    capture.start(MockAudioDevice.DEVICE_ID)
    capture.produce(duration_ms=60, chunk_ms=20)
    captured_speech = buffer.drain()

    # Build a realistic session stream: silence -> wake -> captured speech -> silence.
    stream = [
        silence_chunk(0, 0),
        wake_chunk(1, 20),
        *[
            make_chunk(2 + idx, 40 + idx * 20, pcm=item.pcm)
            for idx, item in enumerate(captured_speech)
        ],
        silence_chunk(5, 100),
    ]
    orchestrator = TranscriptionOrchestrator()
    pipeline = SpeechPipeline(
        session_id=SESSION_ID,
        correlation_id=CORRELATION_ID,
        config=AudioConfig(wake_required=True, vad_min_speech_ms=40),
        orchestrator=orchestrator,
    )
    result = pipeline.process_chunks(stream, timestamp=FIXED_TS, final=True)

    assert [(e.kind, e.sequence_id, e.at_ms) for e in result.speech_events] == [
        ("wake", 0, 20),
        ("speech_start", 1, 40),
        ("speech_end", 2, 100),
    ]
    assert [c.sequence_id for c in result.utterance_chunks] == [2, 3, 4]
    segments = orchestrator.get_segments()
    assert len(segments) == 1
    assert segments[0].session_id == SESSION_ID
    assert segments[0].start_ms == 40
    assert segments[0].end_ms == 100
    assert orchestrator.get_transcript_text() == "Hello from the mock voicebot."

    capture.cancel()
    assert len(buffer) == 0


def test_multi_turn_rewake_keeps_monotonic_speech_sequence_ids() -> None:
    pipeline, orch = build_pipeline(wake_required=True, silence_timeout_ms=40)
    assert orch is not None

    # Turn 1: wake then silence timeout -> closes listening without speech.
    pipeline.process_chunks(
        [wake_chunk(0, 0), silence_chunk(1, 20), silence_chunk(2, 40)],
        timestamp=FIXED_TS,
    )
    assert pipeline.listening is False
    assert pipeline.silence_timeouts == 1

    # Turn 2: new wake -> speech -> silence -> W2 handoff.
    result = pipeline.process_chunks(
        [
            wake_chunk(3, 60),
            make_chunk(4, 80),
            make_chunk(5, 100),
            silence_chunk(6, 120),
        ],
        timestamp=FIXED_TS,
    )
    assert [(e.kind, e.sequence_id, e.at_ms) for e in pipeline.events] == [
        ("wake", 0, 0),
        ("wake", 1, 60),
        ("speech_start", 2, 80),
        ("speech_end", 3, 120),
    ]
    assert [c.sequence_id for c in result.utterance_chunks] == [4, 5]
    segments = orch.get_segments()
    assert len(segments) == 1
    assert (segments[0].start_ms, segments[0].end_ms) == (80, 120)


def test_week3_demo_runs_in_mock_mode(capsys: pytest.CaptureFixture[str]) -> None:
    assert demo_main([]) == 0
    out = capsys.readouterr().out
    assert "kind=wake" in out
    assert "kind=speech_start" in out
    assert "kind=speech_end" in out
    assert "Hello from the mock voicebot." in out
    assert "recovery reconnects=1" in out
    assert "cancelled=True" in out


def _speech(seq: int, start_ms: int) -> AudioChunk:
    return make_chunk(seq, start_ms)


def test_short_pause_between_words_stays_one_utterance_with_default_hangover() -> None:
    """With the real 400 ms default, a 60 ms pause does not end the utterance."""
    orch = TranscriptionOrchestrator()
    pipeline = SpeechPipeline(
        session_id=SESSION_ID,
        correlation_id=CORRELATION_ID,
        config=AudioConfig(wake_required=False),
        orchestrator=orch,
    )
    chunks = [_speech(0, 0), _speech(1, 20), _speech(2, 40)]
    chunks += [silence_chunk(3, 60), silence_chunk(4, 80), silence_chunk(5, 100)]
    chunks += [_speech(6, 120), _speech(7, 140), _speech(8, 160)]
    chunks += [silence_chunk(9 + i, 180 + 20 * i) for i in range(20)]

    result = pipeline.process_chunks(chunks, timestamp=FIXED_TS)

    assert [(e.kind, e.at_ms) for e in result.speech_events] == [
        ("speech_start", 0),
        ("speech_end", 180),
    ]
    # The pause chunks belong to the utterance; trailing silence does not.
    assert [c.sequence_id for c in result.utterance_chunks] == list(range(9))
    assert len(orch.get_segments()) == 1


def test_pause_longer_than_hangover_splits_into_two_utterances() -> None:
    pipeline = SpeechPipeline(
        session_id=SESSION_ID,
        correlation_id=CORRELATION_ID,
        config=AudioConfig(wake_required=False, speech_end_silence_ms=100),
    )
    chunks = [_speech(0, 0), _speech(1, 20), _speech(2, 40)]
    chunks += [silence_chunk(3 + i, 60 + 20 * i) for i in range(5)]  # 100 ms
    chunks += [_speech(8, 160), _speech(9, 180), _speech(10, 200)]
    chunks += [silence_chunk(11 + i, 220 + 20 * i) for i in range(5)]

    result = pipeline.process_chunks(chunks, timestamp=FIXED_TS)

    assert [(e.kind, e.at_ms) for e in result.speech_events] == [
        ("speech_start", 0),
        ("speech_end", 60),
        ("speech_start", 160),
        ("speech_end", 220),
    ]
    assert [e.sequence_id for e in result.speech_events] == [0, 1, 2, 3]


def test_held_wake_score_fires_once_until_detector_drops_below_threshold() -> None:
    """Streaming wake models keep a high score for several frames; one wake only."""
    high = {seq: 0.9 for seq in range(0, 8)}
    high.update({seq: 0.9 for seq in range(9, 11)})
    detector = MockWakeWordDetector(score_by_sequence=high)
    pipeline, _ = build_pipeline(
        wake_required=True,
        silence_timeout_ms=40,
        with_orchestrator=False,
        wake_detector=detector,
    )

    # Chunks 0-7 score high: wake once, listening times out at 40 ms of silence,
    # and the still-high score must not wake it again.
    first = pipeline.process_chunks(
        [silence_chunk(i, 20 * i) for i in range(8)], timestamp=FIXED_TS
    )
    assert [e.kind for e in first.speech_events] == ["wake"]
    assert pipeline.listening is False

    # Chunk 8 scores 0 and re-arms the gate; chunk 9 is a new spoken wake word.
    second = pipeline.process_chunks(
        [silence_chunk(8, 160), silence_chunk(9, 180), silence_chunk(10, 200)],
        timestamp=FIXED_TS,
    )
    assert [(e.kind, e.at_ms) for e in second.speech_events] == [("wake", 180)]
    assert [e.sequence_id for e in pipeline.events] == [0, 1]


def test_long_idle_silence_keeps_vad_window_bounded() -> None:
    seen_sizes: list[int] = []
    real_vad = MockVAD(threshold=0.1, min_speech_ms=40)

    class RecordingVAD:
        def detect(self, chunks: list[AudioChunk]) -> list[SpeechSpan]:
            seen_sizes.append(len(chunks))
            return real_vad.detect(chunks)

    pipeline = SpeechPipeline(
        session_id=SESSION_ID,
        correlation_id=CORRELATION_ID,
        config=AudioConfig(wake_required=False),
        vad=RecordingVAD(),
    )
    silence = [silence_chunk(i, 20 * i) for i in range(500)]  # 10 s of silence
    result = pipeline.process_chunks(silence, timestamp=FIXED_TS)

    assert result.speech_events == []
    assert len(seen_sizes) == 500
    assert max(seen_sizes) <= 3


def _install_fake_openwakeword(
    monkeypatch: pytest.MonkeyPatch,
    *,
    installed: dict[str, bool],
    download_error: Exception | None = None,
) -> list[list[str]]:
    downloads: list[list[str]] = []

    class FakeModel:
        def __init__(self, *, wakeword_models: list[str], inference_framework: str):
            if not installed["value"]:
                raise FileNotFoundError("hey_jarvis_v0.1.onnx failed to load")

        def predict(self, _samples: object) -> dict[str, float]:
            return {"hey_jarvis": 0.8}

    def download_models(*, model_names: list[str]) -> None:
        downloads.append(model_names)
        if download_error is not None:
            raise download_error
        installed["value"] = True

    fake_pkg = types.ModuleType("openwakeword")
    fake_model = types.ModuleType("openwakeword.model")
    fake_utils = types.ModuleType("openwakeword.utils")
    fake_model.Model = FakeModel  # type: ignore[attr-defined]
    fake_utils.download_models = download_models  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openwakeword", fake_pkg)
    monkeypatch.setitem(sys.modules, "openwakeword.model", fake_model)
    monkeypatch.setitem(sys.modules, "openwakeword.utils", fake_utils)
    return downloads


def test_openwakeword_downloads_missing_model_once_then_detects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed = {"value": False}
    downloads = _install_fake_openwakeword(monkeypatch, installed=installed)

    detector = OpenWakeWordDetector(threshold=0.5)
    first = detector.detect(make_chunk(0, 0))
    second = detector.detect(make_chunk(1, 20))

    assert downloads == [["hey_jarvis"]]
    assert first is not None and first.score == pytest.approx(0.8)
    assert second is not None and second.at_ms == 20


@pytest.mark.parametrize(
    ("auto_download", "download_error", "expected_downloads"),
    [(False, None, []), (True, OSError("network down"), [["hey_jarvis"]])],
)
def test_openwakeword_missing_model_gives_safe_error(
    monkeypatch: pytest.MonkeyPatch,
    auto_download: bool,
    download_error: Exception | None,
    expected_downloads: list[list[str]],
) -> None:
    downloads = _install_fake_openwakeword(
        monkeypatch, installed={"value": False}, download_error=download_error
    )
    detector = OpenWakeWordDetector(auto_download=auto_download)

    with pytest.raises(AudioDeviceError) as err:
        detector.detect(make_chunk(0, 0))

    assert err.value.code == "AUDIO_WAKE_MODEL_UNAVAILABLE"
    assert "onnx" not in str(err.value).lower()
    assert "network" not in str(err.value).lower()
    assert downloads == expected_downloads


class _FakeSilero:
    """Stands in for openwakeword.vad.VAD: scores in call order, records calls."""

    def __init__(self, scores: list[float]) -> None:
        self._scores = iter(scores)
        self.calls: list[tuple[int, int]] = []

    def predict(self, samples: object, frame_size: int) -> float:
        self.calls.append((len(samples), frame_size))  # type: ignore[arg-type]
        return next(self._scores)


def test_silero_vad_builds_spans_from_probabilities_scoring_each_chunk_once() -> None:
    model = _FakeSilero([0.1, 0.9, 0.8, 0.95, 0.7, 0.2, 0.1])
    vad = SileroVAD(model=model, threshold=0.5, min_speech_ms=60)
    chunks = [silence_chunk(i, 20 * i) for i in range(7)]

    # The pipeline calls detect on a growing window; Silero is stateful, so
    # every chunk must be scored exactly once and in order.
    for end in range(1, 8):
        spans = vad.detect(chunks[:end])

    assert spans == [SpeechSpan(SESSION_ID, 20, 100)]
    assert model.calls == [(320, 320)] * 7


def test_silero_vad_ignores_bursts_shorter_than_min_speech() -> None:
    vad = SileroVAD(model=_FakeSilero([0.9, 0.1, 0.9, 0.9, 0.1]), min_speech_ms=40)
    spans = vad.detect([silence_chunk(i, 20 * i) for i in range(5)])
    assert spans == [SpeechSpan(SESSION_ID, 40, 80)]


def test_create_vad_uses_silero_for_mic_and_mock_energy_vad_otherwise() -> None:
    assert type(create_vad(AudioConfig())) is MockVAD
    assert type(create_vad(AudioConfig(audio_source="mic"))) is SileroVAD
    assert type(create_vad(AudioConfig(audio_source="mic", vad_provider="mock"))) is (
        MockVAD
    )
    assert type(create_vad(AudioConfig(vad_provider="silero"))) is SileroVAD


def test_silero_vad_without_audio_extra_gives_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "openwakeword.vad", None)
    vad = SileroVAD()
    with pytest.raises(AudioDeviceError) as err:
        vad.detect([silence_chunk(0, 0)])
    assert err.value.code == "AUDIO_DEPENDENCY_MISSING"


def test_idle_window_trim_keeps_enough_audio_for_the_active_vad_minimum() -> None:
    """A VAD needing 100 ms of speech must still see a 100 ms run after trimming."""
    probs = [0.0] * 10 + [0.9] * 6 + [0.0] * 25
    pipeline = SpeechPipeline(
        session_id=SESSION_ID,
        correlation_id=CORRELATION_ID,
        config=AudioConfig(wake_required=False, vad_min_speech_ms=40),
        vad=SileroVAD(model=_FakeSilero(probs), min_speech_ms=100),
    )
    chunks = [silence_chunk(i, 20 * i) for i in range(len(probs))]
    result = pipeline.process_chunks(chunks, timestamp=FIXED_TS)
    assert [(e.kind, e.at_ms) for e in result.speech_events] == [
        ("speech_start", 200),
        ("speech_end", 320),
    ]
