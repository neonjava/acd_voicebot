"""Bounded context builder: freshness, relevance, recency and a token budget.

Token count is approximated as ceil(characters / 4), at least 1 per item. This
is a documented estimate, not a real tokenizer. Item text is never rewritten or
truncated, so source references stay exact; an item that does not fit is left
out instead.
"""

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.contracts.reasoning import ContextItem, ScreenContext
from app.contracts.transcription import TranscriptSegment
from app.reasoning.context import context_item_from_transcript

_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {"the", "and", "for", "are", "was", "what", "with", "this", "that", "does"}
)


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{name} must be timezone-aware UTC")


def approx_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def _keywords(text: str) -> set[str]:
    return {
        word
        for word in _WORD.findall(text.lower())
        if len(word) >= 3 and word not in _STOPWORDS
    }


@dataclass(frozen=True)
class ContextCandidate:
    item: ContextItem
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.item, ContextItem):
            raise TypeError("item must be a ContextItem")
        _require_utc(self.observed_at, "observed_at")


@dataclass(frozen=True)
class BuiltContext:
    items: list[ContextItem]
    used_tokens: int
    token_budget: int
    dropped_stale: list[str] = field(default_factory=list)
    dropped_over_budget: list[str] = field(default_factory=list)
    dropped_duplicate: list[str] = field(default_factory=list)


def candidates_from_screen(context: ScreenContext) -> list[ContextCandidate]:
    return [
        ContextCandidate(item=item, observed_at=context.captured_at)
        for item in context.items
    ]


def candidates_from_transcript(
    segments: Iterable[TranscriptSegment], *, session_started_at: datetime
) -> list[ContextCandidate]:
    """Map final W2 segments; observed time is session start + segment end."""
    _require_utc(session_started_at, "session_started_at")
    return [
        ContextCandidate(
            item=context_item_from_transcript(segment),
            observed_at=session_started_at + timedelta(milliseconds=segment.end_ms),
        )
        for segment in segments
        if segment.is_final
    ]


def build_context(
    candidates: Sequence[ContextCandidate],
    *,
    question: str,
    now: datetime,
    token_budget: int = 512,
    max_age_ms: int = 300_000,
    max_items: int = 20,
) -> BuiltContext:
    """Select fresh, relevant, recent items that fit the token budget.

    1. Drop items older than ``max_age_ms`` or dated after ``now`` (stale).
    2. Keep only the newest copy of each item ID (duplicates).
    3. Rank by keyword overlap with the question, then newest first, then ID.
    4. Add items in rank order while they fit the budget and ``max_items``.
    5. Return the chosen items in chronological order.
    """
    _require_utc(now, "now")
    for value, name in (
        (token_budget, "token_budget"),
        (max_age_ms, "max_age_ms"),
        (max_items, "max_items"),
    ):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be nonblank")

    oldest = now - timedelta(milliseconds=max_age_ms)
    stale: list[str] = []
    newest: dict[str, ContextCandidate] = {}
    duplicate: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, ContextCandidate):
            raise TypeError("candidates must be ContextCandidate values")
        item_id = candidate.item.item_id
        if candidate.observed_at < oldest or candidate.observed_at > now:
            stale.append(item_id)
            continue
        current = newest.get(item_id)
        if current is None:
            newest[item_id] = candidate
        else:
            duplicate.append(item_id)
            if candidate.observed_at > current.observed_at:
                newest[item_id] = candidate

    question_words = _keywords(question)
    ranked = sorted(
        newest.values(),
        key=lambda c: (
            -len(question_words & _keywords(c.item.text)),
            -c.observed_at.timestamp(),
            c.item.item_id,
        ),
    )

    chosen: list[ContextCandidate] = []
    over_budget: list[str] = []
    used = 0
    for candidate in ranked:
        cost = approx_tokens(candidate.item.text)
        if len(chosen) >= max_items or used + cost > token_budget:
            over_budget.append(candidate.item.item_id)
            continue
        chosen.append(candidate)
        used += cost

    chosen.sort(key=lambda c: (c.observed_at, c.item.item_id))
    return BuiltContext(
        items=[c.item for c in chosen],
        used_tokens=used,
        token_budget=token_budget,
        dropped_stale=stale,
        dropped_over_budget=over_budget,
        dropped_duplicate=duplicate,
    )
