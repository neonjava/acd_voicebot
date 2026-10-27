"""FastAPI application for SDE 1 Voicebot Backend."""

import logging
import re
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import settings
from app.contracts.common import ErrorEnvelope
from app.contracts.sessions import MockSessionRequest, MockSessionResponse
from app.sessions.service import session_service

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("voicebot.backend")

CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

app = FastAPI(
    title="SDE 1 Voicebot Backend",
    version="1.0.0",
    description="Backend API and session orchestrator for SDE 1 Voicebot",
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next: Any) -> Response:
    """Validate/propagate X-Correlation-ID and assign unique X-Request-ID."""
    request_id = str(uuid.uuid4())
    incoming_corr_id = request.headers.get("X-Correlation-ID")

    # Generate a fresh fallback correlation ID
    generated_corr_id = f"corr-{uuid.uuid4().hex[:16]}"

    if incoming_corr_id is not None:
        if not CORRELATION_ID_PATTERN.match(incoming_corr_id):
            # Invalid supplied correlation ID -> safe 422 with new correlation ID
            error_envelope = ErrorEnvelope(
                code="INVALID_CORRELATION_ID",
                message_safe_for_user="Invalid X-Correlation-ID header provided.",
                retryable=False,
                correlation_id=generated_corr_id,
                details_redacted={"header": "X-Correlation-ID"},
            )
            response = JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content=error_envelope.model_dump(mode="json"),
            )
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Correlation-ID"] = generated_corr_id
            return response
        effective_corr_id = incoming_corr_id
    else:
        effective_corr_id = generated_corr_id

    # Attach IDs to request state for handlers
    request.state.request_id = request_id
    request.state.correlation_id = effective_corr_id

    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Unhandled server error [request_id=%s correlation_id=%s]: %s",
            request_id,
            effective_corr_id,
            type(exc).__name__,
        )
        error_envelope = ErrorEnvelope(
            code="INTERNAL_SERVER_ERROR",
            message_safe_for_user="An internal server error occurred.",
            retryable=False,
            correlation_id=effective_corr_id,
            details_redacted={},
        )
        response = JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_envelope.model_dump(mode="json"),
        )

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Correlation-ID"] = effective_corr_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Normalize input validation errors into safe ErrorEnvelope without leaks."""
    corr_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:16]}")
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    details = {}
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []))
        details[loc or "body"] = err.get("msg", "Validation error")

    error_envelope = ErrorEnvelope(
        code="VALIDATION_ERROR",
        message_safe_for_user="The request payload was invalid.",
        retryable=False,
        correlation_id=corr_id,
        details_redacted=details,
    )
    response = JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_envelope.model_dump(mode="json"),
    )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Correlation-ID"] = corr_id
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    """Format HTTPExceptions into ErrorEnvelope."""
    corr_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:16]}")
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    message = (
        str(exc.detail) if isinstance(exc.detail, str) else "An HTTP error occurred."
    )
    error_envelope = ErrorEnvelope(
        code=f"HTTP_{exc.status_code}",
        message_safe_for_user=message,
        retryable=exc.status_code >= 500,
        correlation_id=corr_id,
        details_redacted={},
    )
    response = JSONResponse(
        status_code=exc.status_code,
        content=error_envelope.model_dump(mode="json"),
    )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Correlation-ID"] = corr_id
    return response


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Health endpoint confirming the server is running."""
    return {"status": "ok", "mode": "mock"}


@app.get("/api/ready")
async def ready() -> dict[str, str]:
    """Readiness endpoint verifying configuration is ready."""
    if not settings.mock_mode:
        # Week 1 requires mock mode; if somehow disabled, signal 503
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mock mode configuration is unavailable.",
        )
    return {"status": "ready", "mode": "mock"}


@app.post(
    "/api/sessions/mock",
    status_code=status.HTTP_201_CREATED,
    response_model=MockSessionResponse,
)
async def create_mock_session(
    request: Request,
    _body: MockSessionRequest,
) -> MockSessionResponse:
    """Create and run a finite mock session emitting audio and transcript events."""
    corr_id = getattr(request.state, "correlation_id", "correlation-demo")
    return session_service.run_mock_session(correlation_id=corr_id)
