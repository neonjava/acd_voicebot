"""OCR/vision adapter interface and a deterministic mock.

The mock reads the synthetic ``text_regions`` of a frame. It does no image
processing, downloads no model and calls no service.
"""

from typing import Protocol
from urllib.parse import quote

from app.contracts.reasoning import ContextItem, ScreenContext, SourceReference
from app.reasoning.capture import SyntheticFrame

MAX_REGIONS = 50


def _region_ref(frame_id: str, region_id: str) -> str:
    """Join both IDs with ``#``, percent-encoding each so pairs cannot collide."""
    return f"{quote(frame_id, safe='')}#{quote(region_id, safe='')}"


class VisionAdapter(Protocol):
    def extract(
        self, frame: SyntheticFrame, *, capture_enabled: bool
    ) -> ScreenContext: ...


class MockVisionAdapter:
    """Turn synthetic text regions into source-linked context items."""

    def __init__(self, *, max_regions: int = MAX_REGIONS) -> None:
        if type(max_regions) is not int or not 0 < max_regions <= MAX_REGIONS:
            raise ValueError(f"max_regions must be an integer from 1 to {MAX_REGIONS}")
        self.max_regions = max_regions

    def extract(self, frame: SyntheticFrame, *, capture_enabled: bool) -> ScreenContext:
        if not isinstance(frame, SyntheticFrame):
            raise TypeError("frame must be a SyntheticFrame")
        if frame.captured_at is None:
            raise ValueError("frame must have a capture time")
        items: list[ContextItem] = []
        for region_id, text in frame.text_regions[: self.max_regions]:
            if not region_id.strip() or not text.strip():
                continue
            ref = _region_ref(frame.frame_id, region_id)
            items.append(
                ContextItem(
                    item_id=ref,
                    text=text,
                    source=SourceReference(
                        source_id=ref,
                        kind="synthetic_screen",
                        locator=ref,
                    ),
                )
            )
        return ScreenContext(
            frame_id=frame.frame_id,
            captured_at=frame.captured_at,
            capture_enabled=capture_enabled,
            items=items,
        )
