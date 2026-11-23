"""Local LLM provider backed by Ollama (https://ollama.com), off by default.

It implements the same ``LLMProvider`` interface as the mock, so
``LLMReasoningAdapter`` keeps all its checks: timeouts, bounded retries and
strict validation of the returned JSON. The trusted system prompt and the
untrusted request JSON are sent as separate chat messages.

Only a loopback address is accepted: nothing leaves the machine. Uses the
existing ``httpx`` dependency.

Errors map onto the adapter's safe errors:
- timeout -> ``TimeoutError`` (retried, then ``REASONING_RETRY_EXHAUSTED``)
- Ollama not running, or a 5xx -> ``ProviderTransientError`` (retried)
- 4xx such as a model that is not pulled -> ``REASONING_PROVIDER_ERROR``
- a reply that is not the expected JSON -> ``REASONING_MALFORMED_OUTPUT``
"""

import os
from urllib.parse import urlsplit

import httpx

from app.reasoning.llm import LLMProvider, MockLLMProvider, ProviderTransientError

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class OllamaUnavailableError(RuntimeError):
    """A non-retryable Ollama failure, e.g. the model is not pulled."""


class OllamaLLMProvider:
    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.Client | None = None,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a nonblank string")
        parts = urlsplit(base_url)
        if parts.scheme != "http" or parts.hostname not in _LOOPBACK_HOSTS:
            raise ValueError("Ollama must run on this machine (http://127.0.0.1)")
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self._client = client if client is not None else httpx.Client()
        self.calls = 0

    def complete(
        self, *, system_prompt: str, request_json: str, timeout_seconds: float
    ) -> str:
        self.calls += 1
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request_json},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
        try:
            response = self._client.post(
                f"{self.base_url}/api/chat", json=payload, timeout=timeout_seconds
            )
        except httpx.TimeoutException as exc:
            raise TimeoutError("ollama timed out") from exc
        except httpx.TransportError as exc:
            raise ProviderTransientError("ollama is not reachable") from exc

        if response.status_code >= 500:
            raise ProviderTransientError(f"ollama returned {response.status_code}")
        if response.status_code >= 400:
            raise OllamaUnavailableError(f"ollama returned {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            return ""
        message = body.get("message") if isinstance(body, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        return content if isinstance(content, str) else ""


def create_llm_provider() -> LLMProvider:
    """Mock by default; Ollama when ``REASONING_LLM_PROVIDER=ollama``.

    ``REASONING_OLLAMA_MODEL`` (default ``qwen2.5:7b``) and
    ``REASONING_OLLAMA_URL`` (default ``http://127.0.0.1:11434``) configure it.
    """
    provider = os.getenv("REASONING_LLM_PROVIDER", "mock").strip().lower()
    if provider == "mock":
        return MockLLMProvider()
    if provider == "ollama":
        return OllamaLLMProvider(
            model=os.getenv("REASONING_OLLAMA_MODEL", DEFAULT_MODEL),
            base_url=os.getenv("REASONING_OLLAMA_URL", DEFAULT_BASE_URL),
        )
    raise ValueError("REASONING_LLM_PROVIDER must be 'mock' or 'ollama'")
