"""Tests for audio capture status, microphone listen control, and TTS speech audio."""

import io
import wave

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.contracts.common import SessionState
from app.contracts.sessions import TurnRequest
from app.main import app
from app.sessions.service import session_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_state():
    session_service.clear()
    yield
    session_service.clear()


def test_get_capture_status_default_state():
    """Initial capture status is idle with mock source and wake word required."""
    sess = session_service.create_session(
        "session-cap-1", initial_state=SessionState.active
    )

    resp = client.get(f"/api/sessions/{sess.session_id}/capture")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "session-cap-1"
    assert data["state"] == "idle"
    assert data["source"] == "mock"
    assert data["wake_required"] is True
    assert data["wake_word"] == "hey_jarvis"


def test_listen_start_and_stop_lifecycle_emits_capture_events():
    """POST /listen updates capture state and emits audio.capture events."""
    sess = session_service.create_session(
        "session-listen", initial_state=SessionState.active
    )

    # 1. Start listening
    resp_start = client.post(
        f"/api/sessions/{sess.session_id}/listen",
        json={"action": "start"},
    )
    assert resp_start.status_code == 200
    assert resp_start.json()["state"] == "listening"

    # 2. Stop listening
    resp_stop = client.post(
        f"/api/sessions/{sess.session_id}/listen",
        json={"action": "stop"},
    )
    assert resp_stop.status_code == 200
    assert resp_stop.json()["state"] == "stopped"

    # Verify event stream
    events = session_service.get_events(sess.session_id)
    capture_events = [e for e in events if e.event_type == "audio.capture"]
    assert len(capture_events) == 2
    assert capture_events[0].payload.state == "listening"
    assert capture_events[1].payload.state == "stopped"


def test_listen_terminal_session_returns_409():
    """POST /listen on a completed or expired session returns 409."""
    sess = session_service.create_session(
        "session-listen-term", initial_state=SessionState.active
    )
    session_service.transition(sess.session_id, SessionState.completed)

    resp = client.post(
        f"/api/sessions/{sess.session_id}/listen",
        json={"action": "start"},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "SESSION_TERMINAL_STATE"


def test_speech_audio_returns_404_when_tts_disabled(monkeypatch):
    """GET /turns/{id}/speech returns 404 TTS_UNAVAILABLE when TTS is disabled."""
    monkeypatch.setattr(settings, "tts_enabled", False)
    sess = session_service.create_session(
        "session-tts-off", initial_state=SessionState.active
    )

    turn = session_service.create_turn(
        sess.session_id,
        TurnRequest(text="hello"),
    )

    resp = client.get(f"/api/sessions/{sess.session_id}/turns/{turn.turn_id}/speech")
    assert resp.status_code == 404
    data = resp.json()
    assert data["code"] == "TTS_UNAVAILABLE"


def test_speech_audio_returns_valid_wav_when_tts_enabled(monkeypatch):
    """GET /turns/{id}/speech returns valid WAV audio bytes when TTS is enabled."""
    monkeypatch.setattr(settings, "tts_enabled", True)
    sess = session_service.create_session(
        "session-tts-on", initial_state=SessionState.active
    )

    turn = session_service.create_turn(
        sess.session_id,
        TurnRequest(text="hello"),
    )

    resp = client.get(f"/api/sessions/{sess.session_id}/turns/{turn.turn_id}/speech")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/wav")
    assert len(resp.content) > 44  # WAV header + PCM data

    # Verify wave header
    with wave.open(io.BytesIO(resp.content), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000


def test_speech_nonexistent_turn_returns_404():
    """Requesting speech for nonexistent turn ID returns 404 TURN_NOT_FOUND."""
    sess = session_service.create_session(
        "session-no-turn", initial_state=SessionState.active
    )

    resp = client.get(f"/api/sessions/{sess.session_id}/turns/turn-missing/speech")
    assert resp.status_code == 404
    assert resp.json()["code"] == "TURN_NOT_FOUND"
