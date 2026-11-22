"""Workflow progress for the session event stream (``workflow.audit``)."""

from collections.abc import Sequence
from datetime import datetime

from app.contracts.common import EventEnvelope
from app.contracts.workflow import AuditEvent


def audit_envelope(
    event: AuditEvent,
    *,
    run_id: str,
    correlation_id: str,
    timestamp: datetime,
) -> EventEnvelope[AuditEvent]:
    """Wrap one audit event as documented in contracts.md (Week 3).

    ``run_id`` separates attempts of the same plan (a resume starts audit
    sequences at zero again), so event IDs stay unique.
    """
    if not run_id.strip():
        raise ValueError("run_id must be nonblank")
    return EventEnvelope[AuditEvent](
        event_id=f"{event.plan_id}-{run_id}-audit-{event.sequence}",
        event_type="workflow.audit",
        session_id=event.session_id,
        correlation_id=correlation_id,
        timestamp=timestamp,
        producer="workflow",
        payload=event,
    )


def audit_envelopes(
    events: Sequence[AuditEvent],
    *,
    run_id: str,
    correlation_id: str,
    timestamp: datetime,
) -> list[EventEnvelope[AuditEvent]]:
    return [
        audit_envelope(
            e, run_id=run_id, correlation_id=correlation_id, timestamp=timestamp
        )
        for e in events
    ]
