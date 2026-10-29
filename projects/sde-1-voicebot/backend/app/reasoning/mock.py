"""Deterministic mock reasoning with no model, network, or tool execution."""

from app.contracts.reasoning import ReasoningRequest, ReasoningResult


def reason(request: ReasoningRequest) -> ReasoningResult:
    """Cite supplied sources; never treat question or context as instructions."""
    if not isinstance(request, ReasoningRequest):
        raise TypeError("request must be a ReasoningRequest")

    source_ids = list(dict.fromkeys(item.source.source_id for item in request.context))
    if source_ids:
        answer = "Mock grounded response based on the supplied source IDs."
    else:
        answer = "Insufficient evidence in the supplied context."

    result = ReasoningResult(
        request_id=request.request_id,
        session_id=request.session_id,
        answer=answer,
        source_ids=source_ids,
        insufficient_evidence=not source_ids,
        prompt_version=request.prompt_version,
    )
    if not set(result.source_ids).issubset(
        {item.source.source_id for item in request.context}
    ):
        raise ValueError("reasoning result cited a source outside the request")
    return result
