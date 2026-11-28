"""Concurrency and parallel session tests ensuring strict event isolation."""

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.contracts.common import SessionState
from app.contracts.sessions import TurnResponse
from app.main import app
from app.sessions.service import session_service

client = TestClient(app)


def test_concurrent_sessions_event_isolation():
    """Verify that multiple concurrent sessions never leak events between each other."""
    session_count = 6
    turns_per_session = 3

    def run_session_worker(session_idx: int) -> tuple[str, list[str]]:
        session_id = f"concurrent-sess-{session_idx}"
        sess = session_service.create_session(
            session_id, initial_state=SessionState.active
        )
        assert sess.session_id == session_id

        turn_ids: list[str] = []
        for t_idx in range(turns_per_session):
            resp = client.post(
                f"/api/sessions/{session_id}/turns",
                json={"text": f"Question {t_idx} from session {session_idx}"},
            )
            assert resp.status_code == 201
            turn = TurnResponse.model_validate(resp.json())
            turn_ids.append(turn.turn_id)

        return session_id, turn_ids

    # Run sessions concurrently
    with ThreadPoolExecutor(max_workers=session_count) as executor:
        results = list(executor.map(run_session_worker, range(session_count)))

    # Verify strict isolation across all sessions
    for session_id, expected_turn_ids in results:
        events = session_service.get_events(session_id, limit=100)
        assert len(events) >= turns_per_session

        for ev in events:
            # Zero event leakage
            assert ev.session_id == session_id

        # Verify all turns recorded belong only to this session
        assistant_turns = [
            ev.payload
            for ev in events
            if ev.event_type == "assistant.turn"
            and isinstance(ev.payload, TurnResponse)
        ]
        recorded_turn_ids = [t.turn_id for t in assistant_turns]
        for expected_id in expected_turn_ids:
            assert expected_id in recorded_turn_ids


def test_concurrent_approval_decisions_are_isolated(monkeypatch):
    """Verify that concurrent approval decisions on sessions remain isolated."""
    from app.agent import tools
    from app.agent.tools import ToolPolicy
    from app.contracts.workflow import ToolSpec

    spec = ToolSpec(
        name="close_app",
        description="Close an application",
        consequential=True,
    )
    policy = ToolPolicy(
        spec=spec,
        scope="system:app:close",
        validate=lambda args, hosts: None,
        idempotent=False,
    )
    monkeypatch.setitem(tools.TOOL_POLICIES, "close_app", policy)
    monkeypatch.setitem(tools.TOOL_SPECS, "close_app", spec)
    orig_invoke = tools.ToolRuntime.invoke
    monkeypatch.setattr(
        tools.ToolRuntime,
        "invoke",
        lambda self, name, args: (
            f"Closed {args.get('app', 'app')}"
            if name == "close_app"
            else orig_invoke(self, name, args)
        ),
    )

    sessions = []
    approvals = []

    for i in range(4):
        sess = session_service.create_session(
            f"sess-appr-conc-{i}", initial_state=SessionState.active
        )
        sessions.append(sess)
        resp = client.post(
            f"/api/sessions/{sess.session_id}/turns",
            json={"text": f"close app-{i}"},
        )
        assert resp.status_code == 201
        turn = TurnResponse.model_validate(resp.json())
        assert len(turn.approvals) == 1
        approvals.append((sess.session_id, turn.approvals[0].approval_id))

    def decide_worker(pair: tuple[str, str]) -> int:
        session_id, approval_id = pair
        resp = client.post(
            f"/api/sessions/{session_id}/approvals/{approval_id}",
            json={"decision": "approve"},
        )
        return resp.status_code

    with ThreadPoolExecutor(max_workers=4) as executor:
        status_codes = list(executor.map(decide_worker, approvals))

    assert status_codes == [200, 200, 200, 200]

    # Verify each session has its own distinct audit event
    for session_id, _ in approvals:
        events = session_service.get_events(session_id, limit=50)
        audit_events = [ev for ev in events if ev.event_type == "workflow.audit"]
        assert len(audit_events) >= 1
        for audit in audit_events:
            assert audit.session_id == session_id
