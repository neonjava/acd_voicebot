"""The context bundle: what the assistant knows besides the user's sentence.

A bundle holds the recent conversation turns, the active app and window title
(passed in by the caller), and the latest screen observations. It is what makes
the co-pilot contextual: "close it" can be resolved from the previous turn.

Bundles are size-bounded. Text is never rewritten or truncated, so source
references stay exact; when the bundle is too large, the oldest turns and then
the oldest observations are left out.

Every piece becomes a ``ContextItem`` with its own source, so reasoning can cite
it. Conversation turns use the existing ``transcript`` kind and the active
window and screen text use ``synthetic_screen``, so W6's validation keeps
working; dedicated kinds need a coordinated contract change.
"""

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from app.contracts.reasoning import ContextItem, SourceReference
from app.reasoning.observations import Observation

Role = Literal["user", "assistant"]
ACTIVE_WINDOW_ID = "active-window"


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{name} must be timezone-aware UTC")


@dataclass(frozen=True)
class Turn:
    turn_id: str
    role: Role
    text: str
    at: datetime

    def __post_init__(self) -> None:
        if not self.turn_id.strip() or not self.text.strip():
            raise ValueError("turn_id and text must be nonblank")
        if self.role not in ("user", "assistant"):
            raise ValueError("role must be 'user' or 'assistant'")
        _require_utc(self.at, "at")


@dataclass(frozen=True)
class ActiveWindow:
    app: str
    title: str

    def __post_init__(self) -> None:
        if not self.app.strip():
            raise ValueError("app must be nonblank")


@dataclass(frozen=True)
class ContextBundle:
    turns: tuple[Turn, ...] = ()
    active_window: ActiveWindow | None = None
    observations: tuple[Observation, ...] = ()
    dropped_turns: tuple[str, ...] = field(default=())
    dropped_observations: int = 0

    def to_context_items(self) -> list[ContextItem]:
        """Each piece as a cite-able, untrusted context item."""
        items: list[ContextItem] = []
        for turn in self.turns:
            items.append(
                ContextItem(
                    item_id=turn.turn_id,
                    text=f"{turn.role}: {turn.text}",
                    source=SourceReference(
                        source_id=turn.turn_id,
                        kind="transcript",
                        locator=f"conversation/{turn.turn_id}",
                    ),
                )
            )
        if self.active_window is not None:
            window = self.active_window
            title = f" - {window.title}" if window.title.strip() else ""
            items.append(
                ContextItem(
                    item_id=ACTIVE_WINDOW_ID,
                    text=f"Active window: {window.app}{title}",
                    source=SourceReference(
                        source_id=ACTIVE_WINDOW_ID,
                        kind="synthetic_screen",
                        locator="active-window",
                    ),
                )
            )
        items.extend(observation.item for observation in self.observations)
        return items

    def size_chars(self) -> int:
        return sum(len(item.text) for item in self.to_context_items())


class ConversationMemory:
    """Recent turns for one session; the oldest are forgotten first."""

    def __init__(self, *, session_id: str, max_turns: int = 20) -> None:
        if not session_id.strip():
            raise ValueError("session_id must be nonblank")
        if type(max_turns) is not int or max_turns <= 0:
            raise ValueError("max_turns must be a positive integer")
        self.session_id = session_id
        self._turns: deque[Turn] = deque(maxlen=max_turns)
        self._counter = 0

    def add(self, role: Role, text: str, *, at: datetime) -> Turn:
        turn = Turn(f"{self.session_id}-turn-{self._counter}", role, text, at)
        self._counter += 1
        self._turns.append(turn)
        return turn

    def recent(self, limit: int) -> list[Turn]:
        if type(limit) is not int or limit < 0:
            raise ValueError("limit must be a nonnegative integer")
        return list(self._turns)[-limit:] if limit else []


def build_bundle(
    turns: Sequence[Turn],
    *,
    active_window: ActiveWindow | None = None,
    observations: Sequence[Observation] = (),
    max_turns: int = 6,
    max_observations: int = 10,
    max_chars: int = 4000,
) -> ContextBundle:
    """Keep the newest turns and observations that fit ``max_chars``.

    The newest turn is always kept (it is what the user just said), even if it
    alone is larger than the budget.
    """
    for value, name in (
        (max_turns, "max_turns"),
        (max_observations, "max_observations"),
        (max_chars, "max_chars"),
    ):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")

    kept_turns = list(turns)[-max_turns:]
    dropped = [t.turn_id for t in list(turns)[: len(turns) - len(kept_turns)]]
    kept_obs = list(observations)[-max_observations:]
    dropped_obs = len(observations) - len(kept_obs)

    def bundle() -> ContextBundle:
        return ContextBundle(
            turns=tuple(kept_turns),
            active_window=active_window,
            observations=tuple(kept_obs),
            dropped_turns=tuple(dropped),
            dropped_observations=dropped_obs,
        )

    current = bundle()
    while current.size_chars() > max_chars:
        if kept_obs:
            kept_obs.pop(0)
            dropped_obs += 1
        elif len(kept_turns) > 1:
            dropped.append(kept_turns.pop(0).turn_id)
        else:
            break
        current = bundle()
    return current


def last_mentioned_app(bundle: ContextBundle) -> str | None:
    """The app a follow-up such as "close it" most likely refers to.

    Deterministic mock heuristic (a real model reads the whole bundle): the top
    program in the most recent assistant answer that listed programs
    ("Top memory: chrome 3.1 GB, ..."), otherwise the active window's app.
    """
    marker = "top memory:"
    for turn in reversed(bundle.turns):
        if turn.role != "assistant":
            continue
        lowered = turn.text.lower()
        start = lowered.find(marker)
        if start == -1:
            continue
        rest = turn.text[start + len(marker) :].strip()
        name = rest.split(",")[0].split()
        if name:
            return name[0]
    if bundle.active_window is not None:
        return bundle.active_window.app
    return None
