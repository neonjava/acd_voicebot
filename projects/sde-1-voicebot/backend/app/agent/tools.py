"""Allow-listed workflow tools and their registry policies.

Each tool has a registry policy: one permission scope, an argument validator and
whether a repeated call is harmless (idempotent). The policy lives here, not in
the plan, so a plan cannot widen what a tool may do.

Week 3 adds two real tools for the co-pilot (docs/product.md, scenarios S2/S3):

- ``system_stats`` (safe, read-only): RAM and CPU usage and the top processes.
- ``open_url`` (safe only for allow-listed sites): opens a page in the browser.

Mock mode is the default: ``invoke_tool`` uses ``MOCK_RUNTIME``, which returns
fixture stats and only records URLs. Real stats and a real browser need a
``ToolRuntime`` built with ``ToolRuntime.real()`` (see ``runtime_from_env``).
"""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.agent.errors import WorkflowPolicyError
from app.agent.system_tools import (
    MockSystemStatsProvider,
    PsutilSystemStatsProvider,
    RecordingUrlOpener,
    SystemStatsProvider,
    UrlOpener,
    WebbrowserUrlOpener,
    format_system_stats,
)
from app.contracts.workflow import ToolSpec

MAX_TEXT_LENGTH = 1000
MAX_URL_LENGTH = 2048
DEFAULT_ALLOWED_HOSTS: frozenset[str] = frozenset({"youtube.com", "github.com"})

ArgumentValidator = Callable[[Mapping[str, str], frozenset[str]], None]


def _invalid(message: str) -> WorkflowPolicyError:
    return WorkflowPolicyError("WORKFLOW_INVALID_ARGUMENTS", message)


def _validate_text(arguments: Mapping[str, str], _hosts: frozenset[str]) -> None:
    if not isinstance(arguments, Mapping) or set(arguments) != {"text"}:
        raise _invalid("tool requires exactly one text argument")
    text = arguments["text"]
    if not isinstance(text, str):
        raise _invalid("tool requires exactly one text argument")
    if not text.strip():
        raise _invalid("tool text must be nonblank")
    if len(text) > MAX_TEXT_LENGTH:
        raise _invalid(f"tool text must be at most {MAX_TEXT_LENGTH} characters")


def _validate_no_arguments(
    arguments: Mapping[str, str], _hosts: frozenset[str]
) -> None:
    if not isinstance(arguments, Mapping) or arguments:
        raise _invalid("tool takes no arguments")


def host_is_allowed(host: str, allowed_hosts: frozenset[str]) -> bool:
    """True for an allow-listed host or one of its subdomains (www.youtube.com)."""
    host = host.lower().rstrip(".")
    return any(
        host == allowed or host.endswith("." + allowed) for allowed in allowed_hosts
    )


def _validate_url(arguments: Mapping[str, str], allowed_hosts: frozenset[str]) -> None:
    if not isinstance(arguments, Mapping) or set(arguments) != {"url"}:
        raise _invalid("open_url requires exactly one url argument")
    url = arguments["url"]
    if not isinstance(url, str) or not url.strip():
        raise _invalid("url must be a nonblank string")
    if len(url) > MAX_URL_LENGTH or any(ch.isspace() for ch in url):
        raise _invalid("url is too long or contains whitespace")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise WorkflowPolicyError(
            "WORKFLOW_URL_NOT_ALLOWED", "only https links can be opened"
        )
    if parts.username is not None or parts.password is not None:
        raise WorkflowPolicyError(
            "WORKFLOW_URL_NOT_ALLOWED", "links with credentials are not allowed"
        )
    if not parts.hostname or not host_is_allowed(parts.hostname, allowed_hosts):
        raise WorkflowPolicyError(
            "WORKFLOW_URL_NOT_ALLOWED", "this site is not on the allow-list"
        )


@dataclass(frozen=True)
class ToolPolicy:
    spec: ToolSpec
    scope: str
    validate: ArgumentValidator
    idempotent: bool


TOOL_POLICIES: dict[str, ToolPolicy] = {
    "echo_text": ToolPolicy(
        spec=ToolSpec(
            name="echo_text", description="Return supplied text", consequential=False
        ),
        scope="text:read",
        validate=_validate_text,
        idempotent=True,
    ),
    "mock_save_note": ToolPolicy(
        spec=ToolSpec(
            name="mock_save_note",
            description="Simulate saving a note without writing it",
            consequential=True,
        ),
        scope="notes:write",
        validate=_validate_text,
        idempotent=False,
    ),
    "system_stats": ToolPolicy(
        spec=ToolSpec(
            name="system_stats",
            description="Read RAM and CPU usage and the top processes by memory",
            consequential=False,
        ),
        scope="system:read",
        validate=_validate_no_arguments,
        idempotent=True,
    ),
    "open_url": ToolPolicy(
        spec=ToolSpec(
            name="open_url",
            description="Open an allow-listed https page in the browser",
            consequential=False,
        ),
        scope="browser:open",
        validate=_validate_url,
        # Opening twice opens two tabs, so it is never retried.
        idempotent=False,
    ),
}

TOOL_SPECS: dict[str, ToolSpec] = {
    name: policy.spec for name, policy in TOOL_POLICIES.items()
}

# In mock mode every tool is harmless, so the default grants every scope.
# Callers can pass a narrower set to the executor.
DEFAULT_MOCK_SCOPES: frozenset[str] = frozenset(
    policy.scope for policy in TOOL_POLICIES.values()
)


def get_policy(tool_name: str) -> ToolPolicy:
    if tool_name not in TOOL_POLICIES:
        raise WorkflowPolicyError("WORKFLOW_UNKNOWN_TOOL", "unknown workflow tool")
    return TOOL_POLICIES[tool_name]


def validate_tool_call(
    tool_name: str,
    arguments: Mapping[str, str],
    *,
    allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_HOSTS,
) -> None:
    """Validate the allow-list and the tool's exact arguments before invocation."""
    get_policy(tool_name).validate(arguments, allowed_hosts)


def check_scope(tool_name: str, granted_scopes: frozenset[str]) -> None:
    """Reject a tool whose registry scope was not granted to this run."""
    policy = get_policy(tool_name)
    if policy.scope not in granted_scopes:
        raise WorkflowPolicyError(
            "WORKFLOW_SCOPE_DENIED", f"scope '{policy.scope}' was not granted"
        )


@dataclass(frozen=True)
class ToolRuntime:
    """Where the real tools get their data and side effects from."""

    stats: SystemStatsProvider = field(default_factory=MockSystemStatsProvider)
    opener: UrlOpener = field(default_factory=RecordingUrlOpener)
    allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_HOSTS
    mode: str = "mock"

    @classmethod
    def real(
        cls, *, allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_HOSTS
    ) -> "ToolRuntime":
        return cls(
            stats=PsutilSystemStatsProvider(),
            opener=WebbrowserUrlOpener(),
            allowed_hosts=allowed_hosts,
            mode="real",
        )

    def invoke(self, tool_name: str, arguments: Mapping[str, str]) -> str:
        """Invoke one validated tool; usable as the executor's ``invoker``."""
        validate_tool_call(tool_name, arguments, allowed_hosts=self.allowed_hosts)
        if tool_name == "echo_text":
            return arguments["text"]
        if tool_name == "mock_save_note":
            return f"Mock note saved: {arguments['text']}"
        if tool_name == "system_stats":
            return format_system_stats(self.stats.snapshot())
        if tool_name == "open_url":
            self.opener.open(arguments["url"])
            return f"Opened {urlsplit(arguments['url']).hostname}"
        raise WorkflowPolicyError("WORKFLOW_UNKNOWN_TOOL", "unknown workflow tool")


MOCK_RUNTIME = ToolRuntime()


def runtime_from_env() -> ToolRuntime:
    """Build the runtime from ``WORKFLOW_TOOLS_MODE`` and ``WORKFLOW_ALLOWED_HOSTS``.

    ``WORKFLOW_TOOLS_MODE`` is ``mock`` (default) or ``real``.
    ``WORKFLOW_ALLOWED_HOSTS`` is a comma-separated list such as
    ``youtube.com,github.com``.
    """
    mode = os.getenv("WORKFLOW_TOOLS_MODE", "mock").strip().lower()
    raw_hosts = os.getenv("WORKFLOW_ALLOWED_HOSTS")
    hosts = DEFAULT_ALLOWED_HOSTS
    if raw_hosts is not None:
        hosts = frozenset(
            host.strip().lower() for host in raw_hosts.split(",") if host.strip()
        )
        if not hosts:
            raise ValueError("WORKFLOW_ALLOWED_HOSTS must list at least one host")
    if mode == "mock":
        return ToolRuntime(allowed_hosts=hosts)
    if mode == "real":
        return ToolRuntime.real(allowed_hosts=hosts)
    raise ValueError("WORKFLOW_TOOLS_MODE must be 'mock' or 'real'")


def invoke_tool(tool_name: str, arguments: Mapping[str, str]) -> str:
    """Invoke an already validated tool in mock mode (no real side effects)."""
    return MOCK_RUNTIME.invoke(tool_name, arguments)
