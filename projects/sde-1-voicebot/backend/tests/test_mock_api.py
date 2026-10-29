"""Route tests for POST /api/sessions/mock, error handling, and fixture validation."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.contracts.common import ErrorEnvelope
from app.contracts.sessions import MockSessionResponse
from app.contracts.transcription import TranscriptEvent, TranscriptSegment
from app.main import app
from app.sessions.service import session_service


@pytest.fixture
def client():
    return TestClient(app)


def fake_w1_w2_modules():
    """Helper creating mock W1 and W2 modules matching team interfaces."""
    fake_pcm = bytes(32000)
    fake_chunks = [MagicMock() for _ in range(50)]

    def fake_transcribe(
        audio_chunks,
        session_id: str,
        correlation_id: str,
        timestamp: datetime | None = None,
    ):
        ts = timestamp or datetime.now(timezone.utc)
        fake_segment = TranscriptSegment(
            segment_id=f"{session_id}-segment-0",
            session_id=session_id,
            sequence_id=0,
            start_ms=0,
            end_ms=1000,
            text="Hello from the mock voicebot.",
            confidence=1.0,
            language="en",
            is_final=True,
        )
        fake_event = TranscriptEvent(
            event_id="event-transcript-0",
            event_type="transcript.segment",
            schema_version="1.0",
            session_id=session_id,
            correlation_id=correlation_id,
            timestamp=ts,
            producer="transcription",
            payload=fake_segment,
        )
        return [fake_event]

    mock_transcriber = MagicMock()
    mock_transcriber.transcribe.side_effect = fake_transcribe

    return {
        "app.audio": MagicMock(),
        "app.audio.source": MagicMock(make_fake_pcm=MagicMock(return_value=fake_pcm)),
        "app.audio.chunker": MagicMock(chunk_pcm=MagicMock(return_value=fake_chunks)),
        "app.transcription": MagicMock(),
        "app.transcription.mock": MagicMock(
            FakeTranscriber=MagicMock(return_value=mock_transcriber)
        ),
    }


def test_post_mock_session_reports_missing_dependency_blocker(client):
    """When W1 or W2 is unavailable, report 503 blocker instead of fakes."""
    # Ensure W1/W2 are treated as unmerged
    with patch("importlib.util.find_spec", return_value=None):
        response = client.post("/api/sessions/mock", json={})
        assert response.status_code == 503
        data = response.json()
        err = ErrorEnvelope.model_validate(data)
        assert err.code == "DEPENDENCY_UNAVAILABLE"
        assert err.retryable is True
        assert "Waiting for integration PR merge" in err.message_safe_for_user


def test_post_mock_session_success_when_dependencies_present(client):
    """POST /api/sessions/mock returns 201 MockSessionResponse when available."""
    with (
        patch("importlib.util.find_spec", return_value=MagicMock()),
        patch.dict("sys.modules", fake_w1_w2_modules()),
    ):
        response = client.post(
            "/api/sessions/mock",
            json={},
            headers={"X-Correlation-ID": "test-corr-abc"},
        )
        assert response.status_code == 201
        assert response.headers["X-Correlation-ID"] == "test-corr-abc"
        assert "X-Request-ID" in response.headers

        data = response.json()
        validated = MockSessionResponse.model_validate(data)
        assert validated.state == "completed"
        assert validated.mode == "mock"
        assert len(validated.events) == 2
        assert validated.events[0].event_type == "audio.chunk"
        assert validated.events[1].event_type == "transcript.segment"


def test_post_mock_session_generates_unique_session_ids(client):
    """Subsequent POST requests must generate distinct session IDs in memory."""
    with (
        patch("importlib.util.find_spec", return_value=MagicMock()),
        patch.dict("sys.modules", fake_w1_w2_modules()),
    ):
        resp1 = client.post("/api/sessions/mock", json={})
        resp2 = client.post("/api/sessions/mock", json={})

        assert resp1.status_code == 201
        assert resp2.status_code == 201

        sid1 = resp1.json()["session_id"]
        sid2 = resp2.json()["session_id"]

        assert sid1 != sid2, "Session IDs must be unique across runtime requests"
        assert session_service.get_session(sid1) is not None
        assert session_service.get_session(sid2) is not None


def test_post_mock_session_rejects_extra_fields(client):
    """POST /api/sessions/mock with unexpected payload returns 422 ErrorEnvelope."""
    response = client.post(
        "/api/sessions/mock",
        json={"unexpected_field": "disallowed"},
    )
    assert response.status_code == 422
    data = response.json()
    err = ErrorEnvelope.model_validate(data)
    assert err.code == "VALIDATION_ERROR"
    assert err.retryable is False
    assert err.details_redacted["body"] == "Unexpected extra field in payload."


def test_validation_error_does_not_echo_secret_keys(client):
    """User-supplied key names or sensitive data must never leak in error details."""
    secret_key = "secret-token-in-key"
    secret_val = "sensitive-credential-value"
    response = client.post(
        "/api/sessions/mock",
        json={secret_key: secret_val},
    )
    assert response.status_code == 422
    assert secret_key not in response.text
    assert secret_val not in response.text
    assert (
        response.json()["details_redacted"]["body"]
        == "Unexpected extra field in payload."
    )


def test_session_fixture_matches_contract():
    """Verify that session_response.json is valid against MockSessionResponse."""
    fixture_path = Path(__file__).parent / "fixtures" / "session_response.json"
    assert fixture_path.exists(), "session_response.json fixture must exist"

    with open(fixture_path, "r", encoding="utf-8") as f:
        content = json.load(f)

    validated = MockSessionResponse.model_validate(content)
    assert validated.session_id == "session-demo"
    assert validated.state == "completed"
    assert validated.mode == "mock"
    assert len(validated.events) == 2
    assert validated.events[0].event_type == "audio.chunk"
    assert validated.events[1].event_type == "transcript.segment"


def test_fixture_matches_service_output():
    """Verify fixture matches run_synthetic_fixture_session output with zero drift."""
    fixture_path = Path(__file__).parent / "fixtures" / "session_response.json"
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))

    baseline_ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    actual_model = session_service.run_synthetic_fixture_session(
        session_id="session-demo",
        correlation_id="correlation-demo",
        timestamp=baseline_ts,
    )
    actual = actual_model.model_dump(mode="json")
    assert actual == expected, "Fixture must not drift from service output"


def test_post_mock_session_rejects_mismatched_event_session_ids(client):
    """Transcriber returning mismatched session ID fails response validation."""
    fake_pcm = bytes(32000)
    fake_chunks = [MagicMock() for _ in range(50)]

    def mismatched_transcribe(
        audio_chunks,
        session_id: str,
        correlation_id: str,
        timestamp: datetime | None = None,
    ):
        ts = timestamp or datetime.now(timezone.utc)
        fake_segment = TranscriptSegment(
            segment_id="other-session-segment-0",
            session_id="other-session",
            sequence_id=0,
            start_ms=0,
            end_ms=1000,
            text="Mismatched transcript text",
            confidence=1.0,
            language="en",
            is_final=True,
        )
        fake_event = TranscriptEvent(
            event_id="event-transcript-mismatched",
            event_type="transcript.segment",
            schema_version="1.0",
            session_id="other-session",
            correlation_id=correlation_id,
            timestamp=ts,
            producer="transcription",
            payload=fake_segment,
        )
        return [fake_event]

    mock_transcriber = MagicMock()
    mock_transcriber.transcribe.side_effect = mismatched_transcribe

    modules = {
        "app.audio": MagicMock(),
        "app.audio.source": MagicMock(make_fake_pcm=MagicMock(return_value=fake_pcm)),
        "app.audio.chunker": MagicMock(chunk_pcm=MagicMock(return_value=fake_chunks)),
        "app.transcription": MagicMock(),
        "app.transcription.mock": MagicMock(
            FakeTranscriber=MagicMock(return_value=mock_transcriber)
        ),
    }

    with (
        patch("importlib.util.find_spec", return_value=MagicMock()),
        patch.dict("sys.modules", modules),
    ):
        response = client.post("/api/sessions/mock", json={})
        assert response.status_code == 500
        data = response.json()
        err = ErrorEnvelope.model_validate(data)
        assert err.code == "INTERNAL_SERVER_ERROR"
        assert err.retryable is False
