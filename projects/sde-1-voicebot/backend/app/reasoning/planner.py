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
cites a source that was not supplied, does not cite the user's request, or
uses a tool the request text itself does not ask for (``requested_tools``, the
same intent rules as ``RuleBasedPlanner``), or takes a step argument from
anywhere but the request (``_arguments_from_request``). The model cannot pass
those checks by citing the request, because they read only the user's own
words.
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
from app.reasoning.bundle import ContextBundle, Turn, resolve_referent
from app.reasoning.llm import LLMProvider, ProviderTransientError

PROMPT_PATH = Path(__file__).parent / "prompts" / "planner_v1.txt"
MAX_RAW_OUTPUT_CHARS = 20_000
MAX_CLARIFY_CHARS = 300
PlanKind = Literal["none", "clarify", "proposal"]

_PRONOUNS = {"it", "that", "this", "them"}
# Things that are not apps: "close this tab" must not close the whole browser.
_NOT_APPS = {
    "tab", "tabs", "file", "files", "page", "pages",
    "document", "documents", "folder", "folders",
}  # fmt: skip
_RAM = re.compile(r"\b(ram|memory)\b|using the most", re.IGNORECASE)
_SEARCH = re.compile(
    r"\bsearch(?:\s+up|\s+for)?\s+(?P<query>.+?)(?:\s+(?:on|in)\s+youtube)?\s*$",
    re.IGNORECASE,
)
# Imperatives count only at the start of the request, after an optional wake
# word and politeness ("jarvis, can you please close it"). A question that
# merely contains the word ("is it close to full?") is not a request.
_LEAD = (
    r"^\s*(?:(?:hey\s+)?jarvis\b[\s,.:!]*)?"
    r"(?:(?:please|(?:can|could|would|will)\s+you)\s+)*"
)
_CLOSE = re.compile(
    _LEAD
    + r"close\s+(?:(?:the|my|your)\s+)?(?P<target>[\w.+-]+)(?:\s+(?P<noun>[\w-]+))?",
    re.IGNORECASE,
)
_OPEN_YOUTUBE = re.compile(_LEAD + r"open\b.*\byoutube\b", re.IGNORECASE)
_NOTE = re.compile(
    _LEAD
    + r"(?:save|make|take|write)\s+(?:a\s+)?note\b"
    + r"(?:\s+(?:that|saying))?[\s:,]*(?P<text>.*)$",
    re.IGNORECASE,
)


def _close_request(text: str) -> tuple[str, bool] | None:
    """``(target, is_app)`` for an imperative close request, else ``None``."""
    match = _CLOSE.search(text)
    if match is None:
        return None
    target = match.group("target")
    noun = (match.group("noun") or "").lower()
    is_app = target.lower() not in _NOT_APPS and not (
        target.lower() in _PRONOUNS and noun in _NOT_APPS
    )
    return target, is_app


def youtube_url(text: str) -> str:
    """The YouTube page an "open YouTube" request asks for, built from its words."""
    if search := _SEARCH.search(text):
        query = search.group("query").strip(" .?!")
        if query:
            return f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    return "https://www.youtube.com/"


def _note_body(text: str) -> str:
    note = _NOTE.search(text)
    body = note.group("text").strip(" .") if note is not None else ""
    return body or text.strip()


def requested_tools(text: str) -> frozenset[str]:
    """The tools the user's own words ask for (deterministic intent rules).

    Shared by both planners: ``RuleBasedPlanner`` acts on these intents and
    ``LLMWorkflowPlanner`` accepts a proposed tool only if it is listed here.
    """
    tools: set[str] = set()
    close = _close_request(text)
    if close is not None and close[1]:
        tools.add("close_app")
    if _NOTE.search(text):
        tools.add("mock_save_note")
    if _OPEN_YOUTUBE.search(text):
        tools.add("open_url")
    if _RAM.search(text):
        tools.add("system_stats")
    return frozenset(tools)


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


def _normalise(text: str) -> str:
    return " ".join(text.casefold().split()).strip(" .")


def _names_app(text: str, app: str) -> bool:
    pattern = rf"(?<![\w.+-]){re.escape(app)}(?![\w.+-])"
    return re.search(pattern, text.casefold()) is not None


def _arguments_from_request(
    tool: str, arguments: Mapping[str, str], request: Turn, bundle: ContextBundle
) -> bool:
    """True when every argument comes from the user's request, not from context.

    A model that follows injected text can keep the tool the user asked for and
    swap its argument (a link, the note text, the app), so arguments are checked
    against the request too. "close it" may resolve to an app named in the
    conversation or the active window, never to screen text.
    """
    text = request.text
    if tool == "system_stats":
        return not arguments
    if tool == "open_url":
        return dict(arguments) == {"url": youtube_url(text)}
    if tool == "mock_save_note":
        if set(arguments) != {"text"}:
            return False
        body = _normalise(arguments["text"])
        return bool(body) and body in _normalise(text)
    if tool == "close_app":
        close = _close_request(text)
        if close is None or set(arguments) != {"app"}:
            return False
        app = arguments["app"].strip().casefold()
        if not app:
            return False
        target = close[0]
        if target.lower() not in _PRONOUNS:
            return app == target.casefold()
        named = [turn.text for turn in bundle.turns if turn.turn_id != request.turn_id]
        if bundle.active_window is not None:
            named.append(bundle.active_window.app)
        return any(_names_app(t, app) for t in named)
    return False


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

        if close := _close_request(text):
            target, is_app = close
            if not is_app:
                return PlanDecision("clarify", message="I can only close apps.")
            if "close_app" not in catalogue:
                return missing_tool()
            extra: tuple[str, ...] = ()
            if target.lower() in _PRONOUNS:
                referent = resolve_referent(bundle)
                if referent is None:
                    return PlanDecision("clarify", message="Which app should I close?")
                target, source_id = referent
                extra = (source_id,)
            step = WorkflowStep(
                step_id="close",
                tool_name="close_app",
                arguments={"app": target},
                requires_approval=True,
            )
            return _proposal(
                summary=f"Close {target}", steps=[step], extra_sources=extra, **common
            )

        if _NOTE.search(text):
            if "mock_save_note" not in catalogue:
                return missing_tool()
            body = _note_body(text)
            step = WorkflowStep(
                step_id="note",
                tool_name="mock_save_note",
                arguments={"text": body[:1000]},
                requires_approval=True,
            )
            return _proposal(
                summary=f"Save a note: {body[:60]}", steps=[step], **common
            )

        if _OPEN_YOUTUBE.search(text):
            if "open_url" not in catalogue:
                return missing_tool()
            step = WorkflowStep(
                step_id="open",
                tool_name="open_url",
                arguments={"url": youtube_url(text)},
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
        # Citing the request is not enough: the model picks its own citations.
        # Every tool must be one the user's own words ask for.
        allowed = requested_tools(request.text)

        steps: list[WorkflowStep] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict):
                return malformed
            tool = raw_step.get("tool_name")
            arguments = raw_step.get("arguments", {})
            if tool not in catalogue:
                return self._unsafe("unknown_tool")
            if tool not in allowed:
                return self._unsafe("not_from_user_request")
            if not isinstance(arguments, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in arguments.items()
            ):
                return malformed
            if not _arguments_from_request(tool, arguments, request, bundle):
                return self._unsafe("argument_not_from_user_request")
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
