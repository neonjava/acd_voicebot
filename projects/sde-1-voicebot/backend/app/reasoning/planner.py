"""Turn a user request plus its context bundle into a workflow proposal.

The planner decides between three outcomes:
- ``none``: no tool needed, answer the question instead;
- ``clarify``: an action was asked but something is missing or impossible;
- ``proposal``: a schema-valid ``WorkflowProposal`` for W4 to validate and run.

A proposal never runs anything: W4 checks every step and asks for approval for
consequential tools.

Prompt-injection defence: only the user's own request can ask for an action.
``RuleBasedPlanner`` reads intent from the request text only, never from
context. ``LLMWorkflowPlanner`` rejects any proposal that uses an unknown tool,
cites a source that was not supplied, or does not cite the user's request.
"""

import json
import math
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import ValidationError

from app.contracts.common import ErrorEnvelope
from app.contracts.workflow import ToolSpec, WorkflowProposal, WorkflowStep
from app.reasoning.bundle import ContextBundle, Turn, last_mentioned_app
from app.reasoning.llm import LLMProvider, ProviderTransientError

PROMPT_PATH = Path(__file__).parent / "prompts" / "planner_v1.txt"
MAX_RAW_OUTPUT_CHARS = 20_000
MAX_CLARIFY_CHARS = 300
PlanKind = Literal["none", "clarify", "proposal"]

_PRONOUNS = {"it", "that", "this", "them"}
_RAM = re.compile(r"\b(ram|memory)\b|using the most", re.IGNORECASE)
_OPEN_YOUTUBE = re.compile(
    r"\bopen\b.*\byoutube\b|\byoutube\b.*\bopen\b", re.IGNORECASE
)
_SEARCH = re.compile(
    r"\bsearch(?:\s+up|\s+for)?\s+(?P<query>.+?)(?:\s+(?:on|in)\s+youtube)?\s*$",
    re.IGNORECASE,
)
_CLOSE = re.compile(r"\bclose\s+(?:the\s+)?(?P<target>[\w.+-]+)", re.IGNORECASE)
_NOTE = re.compile(
    r"\b(?:save|make|take|write)\s+(?:a\s+)?note\b(?:\s+(?:that|saying))?[\s:,]*(?P<text>.*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PlanDecision:
    kind: PlanKind
    proposal: WorkflowProposal | None = None
    message: str = ""
    error: ErrorEnvelope | None = None


def default_catalogue() -> dict[str, ToolSpec]:
    """The tools W4 currently registers (read-only view of its registry)."""
    from app.agent.tools import TOOL_SPECS

    return dict(TOOL_SPECS)


def _require_request(request: Turn) -> None:
    if not isinstance(request, Turn) or request.role != "user":
        raise ValueError("request must be the user's turn")


def _proposal(
    *,
    request: Turn,
    session_id: str,
    correlation_id: str,
    proposal_id: str | None,
    summary: str,
    steps: list[WorkflowStep],
    extra_sources: tuple[str, ...] = (),
) -> PlanDecision:
    sources = list(dict.fromkeys((request.turn_id, *extra_sources)))
    return PlanDecision(
        "proposal",
        proposal=WorkflowProposal(
            proposal_id=proposal_id or f"proposal-{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            correlation_id=correlation_id,
            summary=summary[:500],
            steps=steps,
            source_ids=sources,
        ),
    )


class RuleBasedPlanner:
    """Deterministic mock planner for tests and demos (no model)."""

    def plan(
        self,
        request: Turn,
        bundle: ContextBundle,
        *,
        catalogue: Mapping[str, ToolSpec],
        session_id: str,
        correlation_id: str,
        proposal_id: str | None = None,
    ) -> PlanDecision:
        _require_request(request)
        text = request.text.strip()
        common = {
            "request": request,
            "session_id": session_id,
            "correlation_id": correlation_id,
            "proposal_id": proposal_id,
        }

        def missing_tool() -> PlanDecision:
            return PlanDecision("clarify", message="I can't do that yet.")

        if close := _CLOSE.search(text):
            if "close_app" not in catalogue:
                return missing_tool()
            target = close.group("target")
            extra: tuple[str, ...] = ()
            if target.lower() in _PRONOUNS:
                resolved = last_mentioned_app(bundle)
                if resolved is None:
                    return PlanDecision("clarify", message="Which app should I close?")
                target = resolved
                extra = tuple(
                    t.turn_id
                    for t in reversed(bundle.turns)
                    if t.role == "assistant" and resolved in t.text
                )[:1]
            step = WorkflowStep(
                step_id="close",
                tool_name="close_app",
                arguments={"app": target},
                requires_approval=True,
            )
            return _proposal(
                summary=f"Close {target}", steps=[step], extra_sources=extra, **common
            )

        if _OPEN_YOUTUBE.search(text):
            if "open_url" not in catalogue:
                return missing_tool()
            url = "https://www.youtube.com/"
            if search := _SEARCH.search(text):
                query = search.group("query").strip(" .?!")
                if query:
                    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
            step = WorkflowStep(
                step_id="open",
                tool_name="open_url",
                arguments={"url": url},
                requires_approval=bool(catalogue["open_url"].consequential),
            )
            return _proposal(summary="Open YouTube", steps=[step], **common)

        if _RAM.search(text):
            if "system_stats" not in catalogue:
                return missing_tool()
            step = WorkflowStep(
                step_id="stats",
                tool_name="system_stats",
                arguments={},
                requires_approval=bool(catalogue["system_stats"].consequential),
            )
            return _proposal(
                summary="Check memory and CPU usage", steps=[step], **common
            )

        if note := _NOTE.search(text):
            if "mock_save_note" not in catalogue:
                return missing_tool()
            body = note.group("text").strip(" .") or text
            step = WorkflowStep(
                step_id="note",
                tool_name="mock_save_note",
                arguments={"text": body[:1000]},
                requires_approval=True,
            )
            return _proposal(
                summary=f"Save a note: {body[:60]}", steps=[step], **common
            )

        return PlanDecision("none")


class LLMWorkflowPlanner:
    """Planner backed by an LLM provider (mock or Ollama), strictly validated."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        timeout_seconds: float = 10.0,
        correlation_id: str = "planner",
    ) -> None:
        if type(timeout_seconds) not in (int, float) or not (
            0 < timeout_seconds < math.inf
        ):
            raise ValueError("timeout_seconds must be a positive finite number")
        self.provider = provider
        self.timeout_seconds = float(timeout_seconds)
        self.correlation_id = correlation_id
        self.system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def _error(self, code: str, message: str, **details: str) -> PlanDecision:
        return PlanDecision(
            "none",
            error=ErrorEnvelope(
                code=code,
                message_safe_for_user=message,
                retryable=False,
                correlation_id=self.correlation_id,
                details_redacted=dict(details),
            ),
        )

    def _unsafe(self, reason: str) -> PlanDecision:
        return self._error(
            "REASONING_UNSAFE_OUTPUT",
            "The planner returned an unsafe plan.",
            reason=reason,
        )

    def plan(
        self,
        request: Turn,
        bundle: ContextBundle,
        *,
        catalogue: Mapping[str, ToolSpec],
        session_id: str,
        correlation_id: str,
        proposal_id: str | None = None,
    ) -> PlanDecision:
        _require_request(request)
        items = bundle.to_context_items()
        known_sources = {item.source.source_id for item in items} | {request.turn_id}
        request_json = json.dumps(
            {
                "request": {"turn_id": request.turn_id, "text": request.text},
                "context": [item.model_dump(mode="json") for item in items],
                "tools": [
                    {
                        "name": name,
                        "description": spec.description,
                        "consequential": spec.consequential,
                    }
                    for name, spec in sorted(catalogue.items())
                ],
            }
        )
        try:
            raw = self.provider.complete(
                system_prompt=self.system_prompt,
                request_json=request_json,
                timeout_seconds=self.timeout_seconds,
            )
        except TimeoutError:
            return self._error("REASONING_TIMEOUT", "The planner timed out.")
        except ProviderTransientError:
            return self._error(
                "REASONING_PROVIDER_UNAVAILABLE", "The planner is not available."
            )
        except Exception:  # noqa: BLE001 - never expose provider exception text
            return self._error("REASONING_PROVIDER_ERROR", "The planner failed.")

        malformed = self._error(
            "REASONING_MALFORMED_OUTPUT", "The planner returned an invalid response."
        )
        if not isinstance(raw, str) or len(raw) > MAX_RAW_OUTPUT_CHARS:
            return malformed
        try:
            data = json.loads(raw)
        except ValueError:
            return malformed
        if not isinstance(data, dict):
            return malformed
        kind = data.get("kind")
        if kind == "none":
            return PlanDecision("none")
        if kind == "clarify":
            message = data.get("message")
            if not isinstance(message, str) or not message.strip():
                return malformed
            return PlanDecision("clarify", message=message.strip()[:MAX_CLARIFY_CHARS])
        if kind != "proposal":
            return malformed

        raw_steps = data.get("steps")
        sources = data.get("source_ids")
        summary = data.get("summary")
        if not isinstance(raw_steps, list) or not isinstance(sources, list):
            return malformed
        if not isinstance(summary, str) or not summary.strip():
            return malformed
        if not all(isinstance(s, str) for s in sources):
            return malformed
        if request.turn_id not in sources:
            return self._unsafe("not_from_user_request")
        if not set(sources) <= known_sources:
            return self._unsafe("unknown_source")

        steps: list[WorkflowStep] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict):
                return malformed
            tool = raw_step.get("tool_name")
            arguments = raw_step.get("arguments", {})
            if tool not in catalogue:
                return self._unsafe("unknown_tool")
            if not isinstance(arguments, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in arguments.items()
            ):
                return malformed
            try:
                steps.append(
                    WorkflowStep(
                        step_id=raw_step.get("step_id"),
                        tool_name=tool,
                        arguments=arguments,
                        depends_on=raw_step.get("depends_on", []),
                        # Approval is decided by the registry, never by the model.
                        requires_approval=bool(catalogue[tool].consequential),
                    )
                )
            except (ValidationError, TypeError):
                return malformed
        try:
            proposal = WorkflowProposal(
                proposal_id=proposal_id or f"proposal-{uuid.uuid4().hex[:12]}",
                session_id=session_id,
                correlation_id=correlation_id,
                summary=summary.strip()[:500],
                steps=steps,
                source_ids=list(dict.fromkeys(sources)),
            )
        except ValidationError:
            return malformed
        return PlanDecision("proposal", proposal=proposal)
