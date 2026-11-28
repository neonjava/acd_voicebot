"""Validation tests for the Week 4 browser-agent contracts."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.contracts.browser import (
    BrowserAction,
    BrowserActionResult,
    PageElement,
    PageSnapshot,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def element(ref: str = "e1", **extra) -> PageElement:  # type: ignore[no-untyped-def]
    return PageElement(
        ref=ref, role="button", name="Login", x=1, y=2, width=3, height=4, **extra
    )


def test_snapshot_rejects_duplicate_refs_and_too_many_elements() -> None:
    PageSnapshot(
        tab_id=1,
        url="https://example.org",
        elements=[element()],
        viewport_width=800,
        viewport_height=600,
        captured_at=NOW,
    )
    with pytest.raises(ValidationError, match="unique"):
        PageSnapshot(
            tab_id=1,
            url="https://example.org",
            elements=[element(), element()],
            viewport_width=800,
            viewport_height=600,
            captured_at=NOW,
        )
    with pytest.raises(ValidationError):
        PageSnapshot(
            tab_id=1,
            url="https://example.org",
            elements=[element(f"e{i}") for i in range(301)],
            viewport_width=800,
            viewport_height=600,
            captured_at=NOW,
        )


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"kind": "click"}, "click needs ref"),
        ({"kind": "type", "ref": "e1"}, "type needs text"),
        ({"kind": "navigate"}, "navigate needs url"),
        ({"kind": "navigate", "url": "http://example.org"}, "https"),
        ({"kind": "navigate", "url": "javascript:alert(1)"}, "https"),
        ({"kind": "press_key", "key": "F12"}, "not allowed"),
        ({"kind": "scroll"}, "scroll needs scroll_y"),
        ({"kind": "teleport"}, "Input should be"),
    ],
)
def test_browser_action_rejects_incomplete_or_unsafe_actions(
    fields: dict, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        BrowserAction(action_id="a1", session_id="s", **fields)


def test_valid_actions_and_results() -> None:
    BrowserAction(action_id="a1", session_id="s", kind="read_page")
    BrowserAction(action_id="a2", session_id="s", kind="type", ref="e1", text="hello")
    BrowserAction(action_id="a3", session_id="s", kind="press_key", key="Enter")
    BrowserActionResult(action_id="a1", ok=True)
    BrowserActionResult(action_id="a1", ok=False, error_code="ELEMENT_NOT_FOUND")
    with pytest.raises(ValidationError):
        BrowserActionResult(action_id="a1", ok=False)
    with pytest.raises(ValidationError):
        BrowserActionResult(action_id="a1", ok=True, error_code="X")
