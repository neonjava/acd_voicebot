"""Exactly two allow-listed tools; both operate only in memory."""

from collections.abc import Mapping

from app.contracts.workflow import ToolSpec

TOOL_SPECS: dict[str, ToolSpec] = {
    "echo_text": ToolSpec(
        name="echo_text", description="Return supplied text", consequential=False
    ),
    "mock_save_note": ToolSpec(
        name="mock_save_note",
        description="Simulate saving a note without writing it",
        consequential=True,
    ),
}


def validate_tool_call(tool_name: str, arguments: Mapping[str, str]) -> None:
    """Validate the allow-list and exact one-field text input before invocation."""
    if tool_name not in TOOL_SPECS:
        raise ValueError("unknown workflow tool")
    if set(arguments) != {"text"} or not isinstance(arguments["text"], str):
        raise ValueError("tool requires exactly one text argument")
    if not arguments["text"].strip():
        raise ValueError("tool text must be nonblank")


def invoke_tool(tool_name: str, arguments: Mapping[str, str]) -> str:
    """Invoke an already validated, harmless mock tool."""
    validate_tool_call(tool_name, arguments)
    text = arguments["text"]
    if tool_name == "echo_text":
        return text
    return f"Mock note saved: {text}"
