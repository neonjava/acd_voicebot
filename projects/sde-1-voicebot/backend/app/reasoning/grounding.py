"""Grounded answers from the context bundle.

The bundle's items go through the existing bounded context builder (freshness,
relevance, token budget) and then the reasoning adapter, which only accepts an
answer that cites supplied sources, or says the evidence is insufficient.
"""

import uuid
from datetime import datetime

from app.contracts.reasoning import ReasoningOutcome, ReasoningRequest
from app.reasoning.bundle import ACTIVE_WINDOW_ID, ContextBundle
from app.reasoning.context_builder import ContextCandidate, build_context
from app.reasoning.llm import LLMReasoningAdapter


def bundle_candidates(
    bundle: ContextBundle, *, now: datetime
) -> list[ContextCandidate]:
    """Bundle items with the time each was observed (active window: now)."""
    times = {turn.turn_id: turn.at for turn in bundle.turns}
    times[ACTIVE_WINDOW_ID] = now
    for observation in bundle.observations:
        times[observation.item.item_id] = observation.observed_at
    return [
        ContextCandidate(item=item, observed_at=times[item.item_id])
        for item in bundle.to_context_items()
    ]


def grounded_answer(
    question: str,
    bundle: ContextBundle,
    *,
    adapter: LLMReasoningAdapter,
    session_id: str,
    now: datetime,
    token_budget: int = 512,
    max_age_ms: int = 300_000,
) -> ReasoningOutcome:
    """Answer from fresh, relevant bundle items, citing the ones used."""
    built = build_context(
        bundle_candidates(bundle, now=now),
        question=question,
        now=now,
        token_budget=token_budget,
        max_age_ms=max_age_ms,
    )
    request = ReasoningRequest(
        request_id=f"request-{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        question=question,
        context=built.items,
    )
    return adapter.reason(request)
