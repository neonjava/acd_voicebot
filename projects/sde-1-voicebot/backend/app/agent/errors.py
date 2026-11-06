"""Typed W4 policy errors with a safe, user-facing envelope."""

from app.contracts.common import ErrorEnvelope


class WorkflowPolicyError(ValueError):
    """A plan or tool call broke a workflow policy before any tool ran.

    It subclasses ValueError so Week 1 callers that catch ValueError keep working.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_envelope(self, correlation_id: str) -> ErrorEnvelope:
        return ErrorEnvelope(
            code=self.code,
            message_safe_for_user=self.message,
            retryable=False,
            correlation_id=correlation_id,
        )


class TransientToolError(Exception):
    """A tool failure that may succeed on retry (only for idempotent tools)."""
