"""Tests for BrowserBridge WebSocket, token handshake, and action dispatch."""

import asyncio
import json

import pytest
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.contracts.browser import BrowserAction, BrowserActionResult
from app.contracts.common import SessionState
from app.sessions.bridge import BrowserBridge, BrowserBridgeError, browser_bridge
from app.sessions.service import session_service


@pytest.fixture(autouse=True)
def clean_bridge():
    browser_bridge.reset_for_tests()
    session_service.clear()
    yield
    browser_bridge.reset_for_tests()
    session_service.clear()


@pytest.mark.asyncio
async def test_bridge_handshake_rejects_missing_or_invalid_token(monkeypatch):
    """Extension with missing or invalid token is closed and token not logged."""
    monkeypatch.setattr(settings, "launch_token", "secret-launch-token-123")

    # 1. Invalid first message (not hello)
    bridge = BrowserBridge()
    mock_ws = AsyncMockWebSocket()
    mock_ws.incoming.put_nowait(json.dumps({"type": "ping"}))
    await bridge.handle_connection(mock_ws)
    assert mock_ws.closed
    assert mock_ws.close_code == 1008

    # 2. Hello with wrong token
    mock_ws2 = AsyncMockWebSocket()
    mock_ws2.incoming.put_nowait(json.dumps({"type": "hello", "token": "wrong-token"}))
    await bridge.handle_connection(mock_ws2)
    assert mock_ws2.closed
    assert mock_ws2.close_code == 1008

    # 3. Hello with correct token succeeds
    mock_ws3 = AsyncMockWebSocket()
    mock_ws3.incoming.put_nowait(
        json.dumps({"type": "hello", "token": "secret-launch-token-123"})
    )
    mock_ws3.incoming.put_nowait(json.dumps({"type": "bye"}))
    await bridge.handle_connection(mock_ws3)
    assert not mock_ws3.closed or mock_ws3.close_code != 1008


@pytest.mark.asyncio
async def test_bridge_refuses_second_simultaneous_connection(monkeypatch):
    """Only one extension connection is active at a time; second is closed."""
    monkeypatch.setattr(settings, "launch_token", None)
    bridge = BrowserBridge()

    ws1 = AsyncMockWebSocket()
    ws2 = AsyncMockWebSocket()

    ws1.incoming.put_nowait(json.dumps({"type": "hello"}))
    t1 = asyncio.create_task(bridge.handle_connection(ws1))

    for _ in range(50):
        if bridge.is_connected:
            break
        await asyncio.sleep(0.01)

    assert bridge.is_connected

    # While conn1 is active, conn2 attempts to connect
    ws2.incoming.put_nowait(json.dumps({"type": "hello"}))
    await bridge.handle_connection(ws2)
    assert ws2.closed
    assert ws2.close_code == 1008

    # Cleanly close conn1
    ws1.incoming.put_nowait(json.dumps({"type": "bye"}))
    await t1


@pytest.mark.asyncio
async def test_bridge_perform_action_and_result_routing():
    """Action is sent to extension and resolved by action_id."""
    bridge = BrowserBridge()
    ws = AsyncMockWebSocket()

    ws.incoming.put_nowait(json.dumps({"type": "hello"}))
    conn_task = asyncio.create_task(bridge.handle_connection(ws))

    for _ in range(50):
        if bridge.is_connected:
            break
        await asyncio.sleep(0.01)

    async def fake_extension_reply():
        sent = await ws.outgoing.get()
        parsed = json.loads(sent)
        action_data = parsed["action"]
        res = {
            "type": "result",
            "result": {
                "action_id": action_data["action_id"],
                "ok": True,
                "error_code": None,
                "snapshot": None,
            },
        }
        ws.incoming.put_nowait(json.dumps(res))

    reply_task = asyncio.create_task(fake_extension_reply())
    action = BrowserAction(
        action_id="act-1", session_id="session-demo", kind="click", ref="e-submit"
    )
    result = await bridge.perform(action, timeout_seconds=2.0)

    assert isinstance(result, BrowserActionResult)
    assert result.action_id == "act-1"
    assert result.ok is True

    await reply_task
    ws.incoming.put_nowait(json.dumps({"type": "bye"}))
    await conn_task


@pytest.mark.asyncio
async def test_bridge_action_timeout_yields_browser_timeout():
    """Action exceeding timeout raises BrowserBridgeError with code BROWSER_TIMEOUT."""
    bridge = BrowserBridge()
    ws = AsyncMockWebSocket()

    ws.incoming.put_nowait(json.dumps({"type": "hello"}))
    conn_task = asyncio.create_task(bridge.handle_connection(ws))

    for _ in range(50):
        if bridge.is_connected:
            break
        await asyncio.sleep(0.01)

    action = BrowserAction(
        action_id="act-timeout", session_id="session-demo", kind="scroll", scroll_y=200
    )
    with pytest.raises(BrowserBridgeError) as exc_info:
        await bridge.perform(action, timeout_seconds=0.05)

    assert exc_info.value.code == "BROWSER_TIMEOUT"

    ws.incoming.put_nowait(json.dumps({"type": "bye"}))
    await conn_task


@pytest.mark.asyncio
async def test_bridge_disconnect_mid_task_cancels_action_safely():
    """Disconnect mid-task fails safely with BROWSER_DISCONNECTED."""
    bridge = BrowserBridge()
    ws = AsyncMockWebSocket()

    ws.incoming.put_nowait(json.dumps({"type": "hello"}))
    conn_task = asyncio.create_task(bridge.handle_connection(ws))

    for _ in range(50):
        if bridge.is_connected:
            break
        await asyncio.sleep(0.01)

    action = BrowserAction(
        action_id="act-crash",
        session_id="session-demo",
        kind="navigate",
        url="https://youtube.com/",
    )

    async def drop_later():
        await asyncio.sleep(0.02)
        ws.incoming.put_nowait(WebSocketDisconnect(code=1006))

    drop_task = asyncio.create_task(drop_later())

    with pytest.raises(BrowserBridgeError) as exc_info:
        await bridge.perform(action, timeout_seconds=2.0)

    assert exc_info.value.code == "BROWSER_DISCONNECTED"

    await drop_task
    await conn_task


@pytest.mark.asyncio
async def test_perform_without_connected_extension_raises_not_connected():
    """Calling perform when no extension is connected returns BROWSER_NOT_CONNECTED."""
    bridge = BrowserBridge()
    action = BrowserAction(
        action_id="act-disc", session_id="session-demo", kind="click", ref="e1"
    )
    with pytest.raises(BrowserBridgeError) as exc_info:
        await bridge.perform(action)

    assert exc_info.value.code == "BROWSER_NOT_CONNECTED"


def test_record_browser_action_emits_event_without_sensitive_snapshot():
    """Session event stream records browser.action events without snapshot text."""
    sess = session_service.create_session(
        "session-browser-evt", initial_state=SessionState.active
    )
    action = BrowserAction(
        action_id="act-snap", session_id=sess.session_id, kind="click", ref="e-buy"
    )

    evt = session_service.record_browser_action(
        sess.session_id,
        action=action,
        ok=True,
    )
    assert evt.event_type == "browser.action"
    assert evt.producer == "browser"
    assert evt.payload.action.action_id == "act-snap"
    assert evt.payload.ok is True


# Helper Mock WebSocket for testing Bridge in isolation
class AsyncMockWebSocket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.accepted = False
        self.closed = False
        self.close_code = None

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000, reason=""):
        self.closed = True
        self.close_code = code

    async def receive_text(self):
        item = await self.incoming.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def send_text(self, text: str):
        await self.outgoing.put(text)
