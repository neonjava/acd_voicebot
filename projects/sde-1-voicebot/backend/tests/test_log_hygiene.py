"""Log hygiene test ensuring sensitive payloads are never logged."""

import json
import logging
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.audio.chunker import chunk_pcm
from app.config import settings
from app.contracts.browser import BrowserAction
from app.contracts.common import SessionState
from app.contracts.reasoning import ContextItem, ScreenContext, SourceReference
from app.main import app
from app.reasoning.observations import ObservationStore
from app.sessions.bridge import BrowserBridge
from app.sessions.service import session_service
from tests.test_browser_bridge import AsyncMockWebSocket

client = TestClient(app)


@pytest.mark.asyncio
async def test_log_hygiene_no_audio_transcript_screen_or_tokens_in_logs(
    caplog: pytest.LogCaptureFixture,
    monkeypatch,
):
    """Assert that raw audio PCM, transcripts, screen bytes, and tokens never leak."""
    caplog.set_level(logging.DEBUG)

    prefix = b"SECRET_AUDIO_PCM_BYTES_FOR_HYGIENE_TEST"
    secret_pcm_data = prefix + b"\x00" * (3200 - len(prefix))
    secret_transcript = "SECRET_USER_TRANSCRIPT_SPOKEN_TEXT_8888"
    secret_screen_text = "SECRET_SCREENSHOT_DATA_SSN_7777"
    secret_launch_token = "SECRET_LAUNCH_TOKEN_XYZ_6666"
    secret_bridge_token = "SECRET_BRIDGE_LAUNCH_TOKEN_5555"
    secret_typed_text = "SECRET_TYPED_PASSWORD_TEXT_4444"

    monkeypatch.setattr(settings, "launch_token", secret_bridge_token)

    # 1. Spoken utterance with secret transcript
    sess = session_service.create_session(
        "sess-hygiene-1", initial_state=SessionState.active
    )
    session_service.process_spoken_utterance(
        sess.session_id,
        text=secret_transcript,
        correlation_id="corr-hygiene-transcript",
    )

    # 2. Process audio chunking with raw PCM
    chunks = chunk_pcm(secret_pcm_data, session_id=sess.session_id, chunk_ms=20)
    assert len(chunks) > 0

    # 3. Add screen observation with secret text to ObservationStore
    now = datetime.now(timezone.utc)
    obs_store = ObservationStore()
    obs_store.give_consent()
    frame = ScreenContext(
        frame_id="frame-1",
        captured_at=now,
        capture_enabled=True,
        items=[
            ContextItem(
                item_id="obs-item-1",
                text=secret_screen_text,
                source=SourceReference(
                    source_id="src-1", locator="calc", kind="synthetic_screen"
                ),
            )
        ],
    )
    decision = obs_store.add_frame(frame, now=now)
    assert decision.status == "accepted"

    # 4. Create turn with launch token in header
    client.post(
        f"/api/sessions/{sess.session_id}/turns",
        json={"text": "What is on my screen?"},
        headers={"Authorization": f"Bearer {secret_launch_token}"},
    )

    # 5. Connect extension bridge with secret bridge token
    bridge = BrowserBridge()
    mock_ws = AsyncMockWebSocket()
    mock_ws.incoming.put_nowait(
        json.dumps({"type": "hello", "token": secret_bridge_token})
    )
    mock_ws.incoming.put_nowait(json.dumps({"type": "bye"}))
    await bridge.handle_connection(mock_ws)

    # 6. Record browser action with sensitive typed text
    type_action = BrowserAction(
        action_id="act-type-pwd",
        session_id=sess.session_id,
        kind="type",
        ref="e-password",
        text=secret_typed_text,
    )
    session_service.record_browser_action(
        sess.session_id,
        action=type_action,
        ok=True,
    )

    # 7. Check all captured logs across all loggers
    log_text = caplog.text

    assert "SECRET_AUDIO_PCM_BYTES" not in log_text, "Audio PCM leaked into logs!"
    assert secret_transcript not in log_text, "Transcript text leaked into logs!"
    assert secret_screen_text not in log_text, "Screen content leaked into logs!"
    assert secret_launch_token not in log_text, "Auth/launch token leaked!"
    assert secret_bridge_token not in log_text, "Bridge token leaked into logs!"
    assert secret_typed_text not in log_text, "Typed text leaked into logs!"
