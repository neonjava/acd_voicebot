"""Browser extension WebSocket bridge (W5) per contracts.md."""

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.config import settings
from app.contracts.browser import BrowserAction, BrowserActionResult

logger = logging.getLogger("voicebot.bridge")


class BrowserBridgeError(Exception):
    """Bridge communication or protocol error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class BrowserBridge:
    """Manages the single active browser extension WebSocket connection.

    Thread-safe and async-safe:
    - Exactly one extension connection active per backend
    - First message must be hello with launch token (never logged)
    - Exactly one action in flight at a time
    - 15s timeout yields BROWSER_ACTION_TIMEOUT
    - Disconnect cancels in-flight actions safely
    - When disconnected, perform returns BROWSER_NOT_CONNECTED
    """

    def __init__(self) -> None:
        self._active_socket: WebSocket | None = None
        self._lock = asyncio.Lock()
        self._pending_action: dict[str, asyncio.Future[BrowserActionResult]] = {}
        self._in_flight_lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        """Check whether an extension WebSocket is currently connected and active."""
        return self._active_socket is not None

    async def handle_connection(self, websocket: WebSocket) -> None:
        """Handle incoming WebSocket connection from the browser extension."""
        async with self._lock:
            if self._active_socket is not None:
                # Refuse second extension connection
                logger.warning(
                    "Second browser extension connection refused: one already active"
                )
                await websocket.close(
                    code=1008, reason="Another extension is already connected"
                )
                return

        await websocket.accept()

        # Enforce handshake: first message must be hello with launch token
        try:
            first_msg_raw = await asyncio.wait_for(
                websocket.receive_text(), timeout=5.0
            )
            first_msg: Any = json.loads(first_msg_raw)
        except Exception:
            logger.warning(
                "Browser extension handshake failed: invalid JSON or timeout"
            )
            await websocket.close(code=1008, reason="Invalid handshake")
            return

        if not isinstance(first_msg, dict) or first_msg.get("type") != "hello":
            logger.warning(
                "Browser extension handshake failed: first message not hello"
            )
            await websocket.close(code=1008, reason="First message must be hello")
            return

        expected_token = settings.launch_token
        if expected_token:
            token = first_msg.get("token")
            if token != expected_token:
                logger.warning(
                    "Browser extension handshake failed: invalid launch token"
                )
                await websocket.close(code=1008, reason="Invalid launch token")
                return

        async with self._lock:
            self._active_socket = websocket
        logger.info("Browser extension bridge connected")

        # Receive loop for results from extension
        try:
            while True:
                msg_raw = await websocket.receive_text()
                try:
                    msg = json.loads(msg_raw)
                except Exception:
                    continue

                if not isinstance(msg, dict):
                    continue

                msg_type = msg.get("type")
                if msg_type == "result":
                    res_data = msg.get("result")
                    if isinstance(res_data, dict):
                        try:
                            action_result = BrowserActionResult.model_validate(res_data)
                            fut = self._pending_action.get(action_result.action_id)
                            if fut and not fut.done():
                                fut.set_result(action_result)
                        except Exception as val_err:
                            logger.warning(
                                "Invalid BrowserActionResult from extension: %s",
                                type(val_err).__name__,
                            )
                elif msg_type == "bye":
                    break
        except (WebSocketDisconnect, Exception) as exc:
            logger.info("Browser extension disconnected: %s", type(exc).__name__)
        finally:
            await self._cleanup(websocket)

    async def _cleanup(self, websocket: WebSocket) -> None:
        """Clean up connection and fail any in-flight pending actions."""
        async with self._lock:
            if self._active_socket == websocket:
                self._active_socket = None

        # Fail any in-flight action with BROWSER_DISCONNECTED
        for action_id, fut in list(self._pending_action.items()):
            if not fut.done():
                fut.set_exception(
                    BrowserBridgeError(
                        "BROWSER_DISCONNECTED",
                        "Browser extension disconnected mid-task",
                    )
                )
        self._pending_action.clear()

    async def perform(
        self,
        action: BrowserAction,
        *,
        timeout_seconds: float | None = None,
    ) -> BrowserActionResult:
        """Dispatch a single BrowserAction to the active extension tab."""
        if not self.is_connected:
            raise BrowserBridgeError(
                "BROWSER_NOT_CONNECTED", "Browser extension is not connected"
            )

        effective_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.browser_timeout_seconds
        )

        async with self._in_flight_lock:
            if not self.is_connected or self._active_socket is None:
                raise BrowserBridgeError(
                    "BROWSER_NOT_CONNECTED", "Browser extension is not connected"
                )

            loop = asyncio.get_running_loop()
            fut: asyncio.Future[BrowserActionResult] = loop.create_future()
            self._pending_action[action.action_id] = fut

            payload = {
                "type": "action",
                "action": action.model_dump(mode="json"),
            }

            try:
                await self._active_socket.send_text(json.dumps(payload))
                result = await asyncio.wait_for(fut, timeout=effective_timeout)
                return result
            except asyncio.TimeoutError as err:
                msg = (
                    f"Browser action '{action.action_id}' "
                    f"timed out after {effective_timeout}s"
                )
                raise BrowserBridgeError("BROWSER_TIMEOUT", msg) from err
            finally:
                self._pending_action.pop(action.action_id, None)

    def reset_for_tests(self) -> None:
        """Reset state cleanly for test fixtures."""
        self._active_socket = None
        self._pending_action.clear()


# Global singleton instance
browser_bridge = BrowserBridge()
