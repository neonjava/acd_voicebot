"""FastAPI application for SDE 1 Voicebot Backend."""

import asyncio
import json
import logging
import re
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.contracts.common import ErrorEnvelope, SessionState
from app.contracts.sessions import (
    MockSessionRequest,
    MockSessionResponse,
    SessionActionRequest,
    SessionCreateRequest,
    SessionEventStreamResponse,
    SessionStateResponse,
)
from app.sessions.logging import (
    StructuredRedactingFormatter,
    current_correlation_id,
    current_request_id,
    current_session_id,
)
from app.sessions.service import (
    IdempotencyConflictError,
    InvalidSessionTransitionError,
    MissingDependencyError,
    SessionAlreadyExistsError,
    SessionExpiredError,
    SessionNotFoundError,
    session_service,
)

# Setup structured and redacted logging
handler = logging.StreamHandler()
handler.setFormatter(StructuredRedactingFormatter())
logging.root.handlers = [handler]
logging.root.setLevel(settings.log_level)
logger = logging.getLogger("voicebot.backend")

CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

app = FastAPI(
    title="SDE 1 Voicebot Backend",
    version="1.0.0",
    description="Backend API and session orchestrator for SDE 1 Voicebot",
)


@app.middleware("http")
async def correlation_and_limits_middleware(
    request: Request, call_next: Any
) -> Response:
    """Validate correlation IDs, payload limits on actual bytes read, and trace IDs."""
    request_id = str(uuid.uuid4())
    incoming_corr_id = request.headers.get("X-Correlation-ID")
    generated_corr_id = f"corr-{uuid.uuid4().hex[:16]}"

    if incoming_corr_id is not None:
        if not CORRELATION_ID_PATTERN.match(incoming_corr_id):
            error_envelope = ErrorEnvelope(
                code="INVALID_CORRELATION_ID",
                message_safe_for_user="Invalid X-Correlation-ID header provided.",
                retryable=False,
                correlation_id=generated_corr_id,
                details_redacted={"header": "X-Correlation-ID"},
            )
            response = JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content=error_envelope.model_dump(mode="json"),
            )
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Correlation-ID"] = generated_corr_id
            return response
        effective_corr_id = incoming_corr_id
    else:
        effective_corr_id = generated_corr_id

    # Check Content-Length header if supplied
    content_length_str = request.headers.get("Content-Length")
    if content_length_str is not None:
        try:
            content_length = int(content_length_str)
            if content_length < 0:
                raise ValueError("Negative Content-Length")
        except ValueError:
            error_envelope = ErrorEnvelope(
                code="INVALID_CONTENT_LENGTH",
                message_safe_for_user="Invalid Content-Length header value.",
                retryable=False,
                correlation_id=effective_corr_id,
                details_redacted={"header": "Content-Length"},
            )
            response = JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=error_envelope.model_dump(mode="json"),
            )
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Correlation-ID"] = effective_corr_id
            return response

        if content_length > settings.max_payload_bytes:
            error_envelope = ErrorEnvelope(
                code="PAYLOAD_TOO_LARGE",
                message_safe_for_user=(
                    f"Request payload exceeds maximum allowed size of "
                    f"{settings.max_payload_bytes} bytes."
                ),
                retryable=False,
                correlation_id=effective_corr_id,
                details_redacted={"limit_bytes": str(settings.max_payload_bytes)},
            )
            response = JSONResponse(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                content=error_envelope.model_dump(mode="json"),
            )
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Correlation-ID"] = effective_corr_id
            return response

    # Enforce payload limit on actual bytes read (including chunked requests)
    if request.method in ("POST", "PUT", "PATCH"):
        body_chunks = []
        bytes_read = 0
        async for chunk in request.stream():
            bytes_read += len(chunk)
            if bytes_read > settings.max_payload_bytes:
                error_envelope = ErrorEnvelope(
                    code="PAYLOAD_TOO_LARGE",
                    message_safe_for_user=(
                        f"Request payload exceeds maximum allowed size of "
                        f"{settings.max_payload_bytes} bytes."
                    ),
                    retryable=False,
                    correlation_id=effective_corr_id,
                    details_redacted={"limit_bytes": str(settings.max_payload_bytes)},
                )
                response = JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content=error_envelope.model_dump(mode="json"),
                )
                response.headers["X-Request-ID"] = request_id
                response.headers["X-Correlation-ID"] = effective_corr_id
                return response
            body_chunks.append(chunk)

        request._body = b"".join(body_chunks)

    # Attach IDs to request state and contextvars
    request.state.request_id = request_id
    request.state.correlation_id = effective_corr_id
    current_correlation_id.set(effective_corr_id)
    current_request_id.set(request_id)

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


# --- Exception Handlers ---


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Normalize input validation errors into safe ErrorEnvelope without leaks."""
    corr_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:16]}")
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    details_redacted: dict[str, str] = {}
    for err in exc.errors():
        err_type = str(err.get("type", ""))
        loc = err.get("loc", ())
        if "extra" in err_type:
            details_redacted["body"] = "Unexpected extra field in payload."
        elif loc and loc[0] == "header":
            details_redacted["header"] = "Invalid header value or format."
        elif loc and loc[0] == "query":
            details_redacted["query"] = "Invalid query parameter."
        else:
            details_redacted["body"] = "Invalid payload field or structure."

    error_envelope = ErrorEnvelope(
        code="VALIDATION_ERROR",
        message_safe_for_user="The request payload was invalid.",
        retryable=False,
        correlation_id=corr_id,
        details_redacted=details_redacted or {"body": "Invalid request payload."},
    )
    response = JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=error_envelope.model_dump(mode="json"),
    )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Correlation-ID"] = corr_id
    return response


@app.exception_handler(MissingDependencyError)
async def missing_dependency_handler(
    request: Request,
    exc: MissingDependencyError,
) -> JSONResponse:
    """Report unmerged upstream dependencies as 503 blockers with safe ErrorEnvelope."""
    corr_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:16]}")
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    error_envelope = ErrorEnvelope(
        code="DEPENDENCY_UNAVAILABLE",
        message_safe_for_user=(
            f"Required upstream dependency is unavailable: {exc.dependency_name}. "
            "Waiting for integration PR merge."
        ),
        retryable=True,
        correlation_id=corr_id,
        details_redacted={"dependency": exc.dependency_name},
    )
    response = JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=error_envelope.model_dump(mode="json"),
    )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Correlation-ID"] = corr_id
    return response


@app.exception_handler(InvalidSessionTransitionError)
async def invalid_transition_handler(
    request: Request,
    exc: InvalidSessionTransitionError,
) -> JSONResponse:
    """Report illegal session state transitions as 409 Conflict with ErrorEnvelope."""
    corr_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:16]}")
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    error_envelope = ErrorEnvelope(
        code="INVALID_STATE_TRANSITION",
        message_safe_for_user=(
            f"Cannot transition session from '{exc.from_state.value}' "
            f"to '{exc.to_state.value}'."
        ),
        retryable=False,
        correlation_id=corr_id,
        details_redacted={
            "from_state": exc.from_state.value,
            "to_state": exc.to_state.value,
        },
    )
    response = JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=error_envelope.model_dump(mode="json"),
    )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Correlation-ID"] = corr_id
    return response


@app.exception_handler(SessionAlreadyExistsError)
async def session_already_exists_handler(
    request: Request,
    exc: SessionAlreadyExistsError,
) -> JSONResponse:
    """Report attempting to overwrite an existing session as 409 Conflict."""
    corr_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:16]}")
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    error_envelope = ErrorEnvelope(
        code="SESSION_ALREADY_EXISTS",
        message_safe_for_user=f"Session already exists: {exc.session_id}",
        retryable=False,
        correlation_id=corr_id,
        details_redacted={"session_id": exc.session_id},
    )
    response = JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=error_envelope.model_dump(mode="json"),
    )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Correlation-ID"] = corr_id
    return response


@app.exception_handler(IdempotencyConflictError)
async def idempotency_conflict_handler(
    request: Request,
    exc: IdempotencyConflictError,
) -> JSONResponse:
    """Report reusing an Idempotency-Key across different sessions as 409 Conflict."""
    corr_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:16]}")
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    error_envelope = ErrorEnvelope(
        code="IDEMPOTENCY_CONFLICT",
        message_safe_for_user=(
            f"Idempotency key '{exc.key}' was already used for session "
            f"'{exc.cached_session_id}' and action '{exc.cached_action}'."
        ),
        retryable=False,
        correlation_id=corr_id,
        details_redacted={
            "idempotency_key": exc.key,
            "cached_session_id": exc.cached_session_id,
            "cached_action": exc.cached_action,
        },
    )
    response = JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=error_envelope.model_dump(mode="json"),
    )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Correlation-ID"] = corr_id
    return response


@app.exception_handler(SessionNotFoundError)
async def session_not_found_handler(
    request: Request,
    exc: SessionNotFoundError,
) -> JSONResponse:
    """Report nonexistent session ID as 404 with ErrorEnvelope."""
    corr_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:16]}")
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    error_envelope = ErrorEnvelope(
        code="SESSION_NOT_FOUND",
        message_safe_for_user=f"Session was not found: {exc.session_id}",
        retryable=False,
        correlation_id=corr_id,
        details_redacted={"session_id": exc.session_id},
    )
    response = JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=error_envelope.model_dump(mode="json"),
    )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Correlation-ID"] = corr_id
    return response


@app.exception_handler(SessionExpiredError)
async def session_expired_handler(
    request: Request,
    exc: SessionExpiredError,
) -> JSONResponse:
    """Report expired session action attempt as 410 Gone with ErrorEnvelope."""
    corr_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:16]}")
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    error_envelope = ErrorEnvelope(
        code="SESSION_EXPIRED",
        message_safe_for_user=f"Session has expired: {exc.session_id}",
        retryable=False,
        correlation_id=corr_id,
        details_redacted={"session_id": exc.session_id},
    )
    response = JSONResponse(
        status_code=status.HTTP_410_GONE,
        content=error_envelope.model_dump(mode="json"),
    )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Correlation-ID"] = corr_id
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Format all Starlette HTTPExceptions (including 404/405) into ErrorEnvelope."""
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


# --- Helper for Idempotency Key Validation ---


def validate_idempotency_key(key: str | None, corr_id: str) -> None:
    """Validate optional Idempotency-Key header against length and char constraints."""
    if key is not None and not IDEMPOTENCY_KEY_PATTERN.match(key):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid Idempotency-Key format. Must be 1-128 chars [A-Za-z0-9_-].",
        )


# --- Endpoints ---


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Health endpoint confirming the server is running."""
    return {"status": "ok", "mode": "mock"}


@app.get("/api/ready")
async def ready() -> dict[str, str]:
    """Readiness endpoint verifying configuration is ready."""
    if not settings.mock_mode:
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
    corr_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:16]}")
    session_id = f"session-{uuid.uuid4().hex[:12]}"
    current_session_id.set(session_id)
    return session_service.run_mock_session(
        session_id=session_id,
        correlation_id=corr_id,
    )


@app.post(
    "/api/sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=SessionStateResponse,
)
async def create_session(
    request: Request,
    body: SessionCreateRequest | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Response:
    """Create a new session, enforcing idempotency and rejecting duplicate IDs."""
    corr_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:16]}")
    validate_idempotency_key(idempotency_key, corr_id)

    req = body or SessionCreateRequest()
    requested_sid = req.session_id

    if idempotency_key:
        cached = session_service.get_idempotent_result(
            idempotency_key,
            "create",
            session_id=requested_sid,
        )
        if cached:
            return JSONResponse(
                status_code=cached.status_code,
                content=cached.response_body,
            )

    initial_st = (
        SessionState.active if req.initial_state == "active" else SessionState.created
    )
    record = session_service.create_session(
        session_id=requested_sid,
        initial_state=initial_st,
    )
    current_session_id.set(record.session_id)
    resp_model = session_service.to_state_response(record)
    content = resp_model.model_dump(mode="json")

    if idempotency_key:
        session_service.record_idempotent_result(
            idempotency_key,
            "create",
            record.session_id,
            status.HTTP_201_CREATED,
            content,
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=content,
    )


@app.get(
    "/api/sessions/{session_id}",
    response_model=SessionStateResponse,
)
async def get_session(
    session_id: str,
) -> SessionStateResponse:
    """Retrieve session state by ID, automatically evaluating TTL expiry."""
    current_session_id.set(session_id)
    record = session_service.get_session(session_id, check_expiry=True)
    if not record:
        raise SessionNotFoundError(session_id)
    return session_service.to_state_response(record)


@app.post(
    "/api/sessions/{session_id}/pause",
    response_model=SessionStateResponse,
)
async def pause_session(
    request: Request,
    session_id: str,
    _body: SessionActionRequest | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Response:
    """Pause an active session. Idempotent command scoped to session."""
    corr_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:16]}")
    current_session_id.set(session_id)
    validate_idempotency_key(idempotency_key, corr_id)

    if idempotency_key:
        cached = session_service.get_idempotent_result(
            idempotency_key, "pause", session_id=session_id
        )
        if cached:
            return JSONResponse(
                status_code=cached.status_code,
                content=cached.response_body,
            )

    record = session_service.pause_session(session_id)
    resp_model = session_service.to_state_response(record)
    content = resp_model.model_dump(mode="json")

    if idempotency_key:
        session_service.record_idempotent_result(
            idempotency_key,
            "pause",
            session_id,
            status.HTTP_200_OK,
            content,
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=content)


@app.post(
    "/api/sessions/{session_id}/resume",
    response_model=SessionStateResponse,
)
async def resume_session(
    request: Request,
    session_id: str,
    _body: SessionActionRequest | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Response:
    """Resume a paused session to active. Idempotent command scoped to session."""
    corr_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:16]}")
    current_session_id.set(session_id)
    validate_idempotency_key(idempotency_key, corr_id)

    if idempotency_key:
        cached = session_service.get_idempotent_result(
            idempotency_key, "resume", session_id=session_id
        )
        if cached:
            return JSONResponse(
                status_code=cached.status_code,
                content=cached.response_body,
            )

    record = session_service.resume_session(session_id)
    resp_model = session_service.to_state_response(record)
    content = resp_model.model_dump(mode="json")

    if idempotency_key:
        session_service.record_idempotent_result(
            idempotency_key,
            "resume",
            session_id,
            status.HTTP_200_OK,
            content,
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=content)


@app.post(
    "/api/sessions/{session_id}/stop",
    response_model=SessionStateResponse,
)
async def stop_session(
    request: Request,
    session_id: str,
    _body: SessionActionRequest | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Response:
    """Stop an active or paused session and mark completed. Scoped to session."""
    corr_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:16]}")
    current_session_id.set(session_id)
    validate_idempotency_key(idempotency_key, corr_id)

    if idempotency_key:
        cached = session_service.get_idempotent_result(
            idempotency_key, "stop", session_id=session_id
        )
        if cached:
            return JSONResponse(
                status_code=cached.status_code,
                content=cached.response_body,
            )

    record = session_service.stop_session(session_id)
    resp_model = session_service.to_state_response(record)
    content = resp_model.model_dump(mode="json")

    if idempotency_key:
        session_service.record_idempotent_result(
            idempotency_key,
            "stop",
            session_id,
            status.HTTP_200_OK,
            content,
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=content)


@app.post(
    "/api/sessions/{session_id}/expire",
    response_model=SessionStateResponse,
)
async def expire_session(
    session_id: str,
) -> SessionStateResponse:
    """Explicitly expire a session."""
    current_session_id.set(session_id)
    record = session_service.expire_session(session_id)
    return session_service.to_state_response(record)


@app.get(
    "/api/sessions/{session_id}/events",
    response_model=SessionEventStreamResponse,
)
async def get_session_events(
    session_id: str,
    from_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> SessionEventStreamResponse:
    """Query ordered session event history with sequence offset and limit."""
    current_session_id.set(session_id)
    record = session_service.get_session(session_id, check_expiry=True)
    if not record:
        raise SessionNotFoundError(session_id)

    events = session_service.get_events(
        session_id, from_sequence=from_sequence, limit=limit
    )
    all_events = session_service._session_events.get(session_id, [])
    total = len(all_events)
    has_more = (from_sequence + len(events)) < total

    return SessionEventStreamResponse(
        session_id=session_id,
        events=events,
        from_sequence=from_sequence,
        total_events=total,
        has_more=has_more,
    )


@app.get("/api/sessions/{session_id}/events/stream")
async def stream_session_events(
    request: Request,
    session_id: str,
    from_sequence: int = Query(default=0, ge=0),
) -> StreamingResponse:
    """Stream ordered session events via SSE, following live until terminal state."""
    current_session_id.set(session_id)
    record = session_service.get_session(session_id, check_expiry=True)
    if not record:
        raise SessionNotFoundError(session_id)

    async def event_generator():
        cursor = from_sequence
        while True:
            if await request.is_disconnected():
                break

            current_events = session_service.get_events(
                session_id, from_sequence=cursor, limit=100
            )
            for evt in current_events:
                evt_data = evt.model_dump(mode="json")
                yield f"event: session.event\ndata: {json.dumps(evt_data)}\n\n"
                cursor += 1

            sess = session_service.get_session(session_id, check_expiry=True)
            if not sess:
                break

            # If terminal state reached, send remaining events and complete
            if sess.state in (
                SessionState.completed,
                SessionState.failed,
                SessionState.expired,
            ):
                remaining = session_service.get_events(
                    session_id, from_sequence=cursor, limit=100
                )
                for evt in remaining:
                    evt_data = evt.model_dump(mode="json")
                    yield f"event: session.event\ndata: {json.dumps(evt_data)}\n\n"
                    cursor += 1

                status_data = json.dumps(
                    {"session_id": session_id, "state": sess.state.value}
                )
                yield f"event: session.status\ndata: {status_data}\n\n"
                break

            await asyncio.sleep(0.05)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
