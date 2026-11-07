"""Provider-neutral LLM adapter with timeout, bounded retry and strict validation.

The trusted system prompt (``prompts/v1.txt``) and the untrusted request JSON
are passed to the provider as separate arguments. The adapter accepts only a
``ReasoningResult`` JSON object that matches the request; anything else becomes
a safe ``ErrorEnvelope``. The default provider is a deterministic mock: no
network, model download or API key.
"""

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Protocol

from pydantic import ValidationError

from app.contracts.common import ErrorEnvelope
from app.contracts.reasoning import ReasoningOutcome, ReasoningRequest, ReasoningResult
from app.reasoning.mock import reason

PROMPT_DIR = Path(__file__).parent / "prompts"
MAX_RAW_OUTPUT_CHARS = 20_000


def load_prompt(version: Literal["v1"] = "v1") -> str:
    return (PROMPT_DIR / f"{version}.txt").read_text(encoding="utf-8")


class ProviderTransientError(Exception):
    """A temporary provider failure that may succeed on retry."""


class LLMProvider(Protocol):
    def complete(
        self, *, system_prompt: str, request_json: str, timeout_seconds: float
    ) -> str:
        """Return a ``ReasoningResult`` JSON object, as the system prompt requires."""
        ...


MockBehavior = Literal["ok", "timeout", "transient", "crash"]


class MockLLMProvider:
    """Deterministic provider for tests and demos.

    ``script`` gives one behavior per call; after the script ends every call is
    ``"ok"``. A plain string in the script is returned verbatim as raw output,
    so tests can feed malformed or unsafe responses. ``latency_seconds`` larger
    than the adapter timeout raises ``TimeoutError`` without sleeping.
    """

    def __init__(
        self,
        script: Sequence[MockBehavior | str] = (),
        *,
        latency_seconds: float = 0.0,
    ) -> None:
        self._script = list(script)
        self.latency_seconds = latency_seconds
        self.calls = 0
        self.last_system_prompt: str | None = None

    def complete(
        self, *, system_prompt: str, request_json: str, timeout_seconds: float
    ) -> str:
        self.calls += 1
        self.last_system_prompt = system_prompt
        behavior = self._script.pop(0) if self._script else "ok"
        if self.latency_seconds > timeout_seconds or behavior == "timeout":
            raise TimeoutError("simulated provider timeout")
        if behavior == "transient":
            raise ProviderTransientError("simulated provider busy")
        if behavior == "crash":
            raise RuntimeError("simulated provider crash /internal/detail")
        if behavior != "ok":
            return behavior
        request = ReasoningRequest.model_validate_json(request_json)
        return reason(request).model_dump_json()


class LLMReasoningAdapter:
    """Call a provider safely and return a ``ReasoningOutcome``."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        timeout_seconds: float = 5.0,
        max_retries: int = 1,
        max_answer_chars: int = 2000,
        correlation_id: str = "reasoning-mock",
    ) -> None:
        if type(timeout_seconds) not in (int, float) or not (
            0 < timeout_seconds < math.inf
        ):
            raise ValueError("timeout_seconds must be a positive finite number")
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("max_retries must be a nonnegative integer")
        if type(max_answer_chars) is not int or max_answer_chars <= 0:
            raise ValueError("max_answer_chars must be a positive integer")
        if not isinstance(correlation_id, str) or not correlation_id.strip():
            raise ValueError("correlation_id must be a nonblank string")
        self.provider = provider if provider is not None else MockLLMProvider()
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = max_retries
        self.max_answer_chars = max_answer_chars
        self.correlation_id = correlation_id
        self.system_prompt = load_prompt("v1")

    def _error(
        self, code: str, message: str, *, retryable: bool, **details: str
    ) -> ErrorEnvelope:
        return ErrorEnvelope(
            code=code,
            message_safe_for_user=message,
            retryable=retryable,
            correlation_id=self.correlation_id,
            details_redacted=dict(details),
        )

    def reason(self, request: ReasoningRequest) -> ReasoningOutcome:
        if not isinstance(request, ReasoningRequest):
            raise TypeError("request must be a ReasoningRequest")

        def outcome(
            attempts: int,
            *,
            result: ReasoningResult | None = None,
            error: ErrorEnvelope | None = None,
        ) -> ReasoningOutcome:
            return ReasoningOutcome(
                request_id=request.request_id,
                session_id=request.session_id,
                result=result,
                error=error,
                attempts=attempts,
            )

        request_json = request.model_dump_json()
        last_code = "UNKNOWN"
        for attempt in range(1, self.max_retries + 2):
            try:
                raw = self.provider.complete(
                    system_prompt=self.system_prompt,
                    request_json=request_json,
                    timeout_seconds=self.timeout_seconds,
                )
            except TimeoutError:
                last_code = "REASONING_TIMEOUT"
                continue
            except ProviderTransientError:
                last_code = "REASONING_PROVIDER_UNAVAILABLE"
                continue
            except Exception:  # noqa: BLE001 - never expose provider exception text
                return outcome(
                    attempt,
                    error=self._error(
                        "REASONING_PROVIDER_ERROR",
                        "The reasoning provider failed.",
                        retryable=False,
                    ),
                )

            result, error = self._validate(raw, request)
            return outcome(attempt, result=result, error=error)

        return outcome(
            self.max_retries + 1,
            error=self._error(
                "REASONING_RETRY_EXHAUSTED",
                "The reasoning provider did not respond in time.",
                retryable=False,
                last_error_code=last_code,
                attempts=str(self.max_retries + 1),
            ),
        )

    def _validate(
        self, raw: object, request: ReasoningRequest
    ) -> tuple[ReasoningResult | None, ErrorEnvelope | None]:
        malformed = self._error(
            "REASONING_MALFORMED_OUTPUT",
            "The reasoning provider returned an invalid response.",
            retryable=False,
        )
        if not isinstance(raw, str) or len(raw) > MAX_RAW_OUTPUT_CHARS:
            return None, malformed
        try:
            result = ReasoningResult.model_validate_json(raw)
        except ValidationError:
            return None, malformed

        reason_code = self._unsafe_reason(result, request)
        if reason_code is not None:
            return None, self._error(
                "REASONING_UNSAFE_OUTPUT",
                "The reasoning provider returned an unsafe response.",
                retryable=False,
                reason=reason_code,
            )
        return result, None

    def _unsafe_reason(
        self, result: ReasoningResult, request: ReasoningRequest
    ) -> str | None:
        if (
            result.request_id != request.request_id
            or result.session_id != request.session_id
        ):
            return "mismatched_ids"
        if result.prompt_version != request.prompt_version:
            return "mismatched_prompt_version"
        allowed = {item.source.source_id for item in request.context}
        if not set(result.source_ids) <= allowed:
            return "unknown_source"
        if len(result.answer) > self.max_answer_chars:
            return "answer_too_long"
        if any(ord(ch) < 32 and ch not in "\n\t" for ch in result.answer):
            return "control_characters"
        return None
