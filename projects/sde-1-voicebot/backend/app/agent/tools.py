"""Exactly two allow-listed tools; both operate only in memory.

Each tool has a registry policy: one permission scope, an exact argument set and
whether a repeated call is harmless (idempotent). The policy lives here, not in
the plan, so a plan cannot widen what a tool may do.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from app.agent.errors import WorkflowPolicyError
from app.contracts.workflow import ToolSpec

MAX_TEXT_LENGTH = 1000


@dataclass(frozen=True)
class ToolPolicy:
    spec: ToolSpec
    scope: str
    argument_names: frozenset[str]
    idempotent: bool


TOOL_POLICIES: dict[str, ToolPolicy] = {
    "echo_text": ToolPolicy(
        spec=ToolSpec(
            name="echo_text", description="Return supplied text", consequential=False
        ),
        scope="text:read",
        argument_names=frozenset({"text"}),
        idempotent=True,
    ),
    "mock_save_note": ToolPolicy(
        spec=ToolSpec(
            name="mock_save_note",
            description="Simulate saving a note without writing it",
            consequential=True,
        ),
        scope="notes:write",
        argument_names=frozenset({"text"}),
        idempotent=False,
    ),
}

TOOL_SPECS: dict[str, ToolSpec] = {
    name: policy.spec for name, policy in TOOL_POLICIES.items()
}

# Both mock tools are harmless, so the mock default grants both scopes.
# Callers can pass a narrower set to the executor.
DEFAULT_MOCK_SCOPES: frozenset[str] = frozenset(
    policy.scope for policy in TOOL_POLICIES.values()
)


def get_policy(tool_name: str) -> ToolPolicy:
    if tool_name not in TOOL_POLICIES:
        raise WorkflowPolicyError("WORKFLOW_UNKNOWN_TOOL", "unknown workflow tool")
    return TOOL_POLICIES[tool_name]


def validate_tool_call(tool_name: str, arguments: Mapping[str, str]) -> None:
    """Validate the allow-list and the exact argument set before invocation."""
    policy = get_policy(tool_name)
    if not isinstance(arguments, Mapping) or set(arguments) != policy.argument_names:
        raise WorkflowPolicyError(
            "WORKFLOW_INVALID_ARGUMENTS", "tool requires exactly one text argument"
        )
    text = arguments["text"]
    if not isinstance(text, str):
        raise WorkflowPolicyError(
            "WORKFLOW_INVALID_ARGUMENTS", "tool requires exactly one text argument"
        )
    if not text.strip():
        raise WorkflowPolicyError(
            "WORKFLOW_INVALID_ARGUMENTS", "tool text must be nonblank"
        )
    if len(text) > MAX_TEXT_LENGTH:
        raise WorkflowPolicyError(
            "WORKFLOW_INVALID_ARGUMENTS",
            f"tool text must be at most {MAX_TEXT_LENGTH} characters",
        )


def check_scope(tool_name: str, granted_scopes: frozenset[str]) -> None:
    """Reject a tool whose registry scope was not granted to this run."""
    policy = get_policy(tool_name)
    if policy.scope not in granted_scopes:
        raise WorkflowPolicyError(
            "WORKFLOW_SCOPE_DENIED", f"scope '{policy.scope}' was not granted"
        )


def invoke_tool(tool_name: str, arguments: Mapping[str, str]) -> str:
    """Invoke an already validated, harmless mock tool."""
    validate_tool_call(tool_name, arguments)
    text = arguments["text"]
    if tool_name == "echo_text":
        return text
    return f"Mock note saved: {text}"
