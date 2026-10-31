"""Show a deterministic request-to-mock-response path."""

from app.contracts.reasoning import ReasoningRequest
from app.reasoning.context import make_synthetic_screen_context
from app.reasoning.mock import reason


def main() -> None:
    frame = make_synthetic_screen_context()
    request = ReasoningRequest(
        request_id="reasoning-demo-0",
        session_id="session-demo",
        question="What does the mock dashboard show?",
        context=frame.items,
    )
    result = reason(request)
    print(f"capture_enabled={frame.capture_enabled}")
    print(f"prompt_version={result.prompt_version}")
    print(f"answer={result.answer}")
    print(f"source_ids={','.join(result.source_ids)}")


if __name__ == "__main__":
    main()
