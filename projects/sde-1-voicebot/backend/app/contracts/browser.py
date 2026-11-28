"""Browser-agent contracts (Week 4): the extension bridge and its actions.

Jarvis works inside the user's own browser through a small extension, like a
browser co-pilot: it reads the page, then clicks, types, navigates and scrolls,
one action at a time. The extension (W1) talks to the backend bridge (W5); the
agent loop (W3) chooses actions; W4 enforces the approval policy; W6 shows the
companion UI.

Page content is untrusted data: it can never become an instruction.
"""

from datetime import datetime
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from app.contracts.common import ContractModel

BrowserActionKind = Literal[
    "read_page", "navigate", "click", "type", "press_key", "scroll", "wait"
]
ALLOWED_KEYS = frozenset(
    {
        "Enter",
        "Tab",
        "Escape",
        "Backspace",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "PageUp",
        "PageDown",
        "Home",
        "End",
        "Space",
    }
)


class PageElement(ContractModel):
    """One interactive element the extension found, addressed by ``ref``."""

    ref: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    role: str = Field(min_length=1, max_length=40)
    name: str = Field(default="", max_length=200)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    editable: bool = False
    sensitive: bool = False  # password, card or one-time-code field


class PageSnapshot(ContractModel):
    """What the agent can see of the current tab (viewport coordinates)."""

    tab_id: int = Field(ge=0)
    url: str = Field(min_length=1, max_length=2048)
    title: str = Field(default="", max_length=300)
    text: str = Field(default="", max_length=20_000)
    elements: list[PageElement] = Field(default_factory=list, max_length=300)
    viewport_width: int = Field(gt=0)
    viewport_height: int = Field(gt=0)
    captured_at: datetime

    @model_validator(mode="after")
    def unique_refs(self) -> Self:
        refs = [element.ref for element in self.elements]
        if len(refs) != len(set(refs)):
            raise ValueError("element refs must be unique")
        return self


class BrowserAction(ContractModel):
    """One step the agent asks the extension to perform."""

    action_id: str = Field(min_length=1, max_length=64, pattern=r"\S")
    session_id: str = Field(min_length=1, pattern=r"\S")
    kind: BrowserActionKind
    ref: str | None = Field(default=None, max_length=32)
    url: str | None = Field(default=None, max_length=2048)
    text: str | None = Field(default=None, max_length=2000)
    key: str | None = None
    scroll_y: int | None = Field(default=None, ge=-5000, le=5000)

    @field_validator("url")
    @classmethod
    def https_only(cls, value: str | None) -> str | None:
        if value is not None and urlsplit(value).scheme != "https":
            raise ValueError("navigate only to https URLs")
        return value

    @model_validator(mode="after")
    def fields_match_kind(self) -> Self:
        needs = {
            "navigate": ("url",),
            "click": ("ref",),
            "type": ("ref", "text"),
            "press_key": ("key",),
            "scroll": ("scroll_y",),
        }.get(self.kind, ())
        for name in needs:
            if getattr(self, name) is None:
                raise ValueError(f"{self.kind} needs {name}")
        if self.key is not None and self.key not in ALLOWED_KEYS:
            raise ValueError("key is not allowed")
        return self


class BrowserActionResult(ContractModel):
    """The extension's answer: success or a safe error, plus a fresh snapshot."""

    action_id: str = Field(min_length=1, max_length=64, pattern=r"\S")
    ok: bool
    error_code: str | None = Field(default=None, max_length=64)
    snapshot: PageSnapshot | None = None

    @model_validator(mode="after")
    def error_when_failed(self) -> Self:
        if self.ok == (self.error_code is not None):
            raise ValueError("a failed result needs error_code; a success has none")
        return self


BridgeMessageType = Literal["hello", "action", "result", "bye"]
