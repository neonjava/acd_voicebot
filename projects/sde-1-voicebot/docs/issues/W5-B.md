# [W5-B] Connect session API to actual W1 and W2 implementations

Suggested owner: **Rakshita**. Hemanth will assign the GitHub issue. Reviewer: **Hemanth**. Estimate: **4–6 focused hours**. Milestone: **Week 1 — Foundation**.

## Before starting

- Repository: `neonjava/acd_voicebot` only. Do not access the original repository.
- The structure PR must be merged into `team/sde-1-voicebot` before branching.
- Prerequisite issues (must be merged before final verification): **W5-A, W1-B, W2-B**.
- Feature branch: `feature/w5-b-implementation`; PR base: `team/sde-1-voicebot`.
- Read root AGENTS.md, team README.md, docs/START_HERE.md, docs/contracts.md and docs/CONNECTIONS.md. The interface specification is a concrete provisional team decision, not provider approval.
- This is initially a documentation/folder scaffold. W5-A creates Python tooling; W6-A creates frontend tooling. Do not assume files already exist.

## Goal

Starting a mock session produces a typed API response from W1→W2, with a documented launcher and shared frontend fixture.

## Files you own for this issue

Paths below are relative to `projects/sde-1-voicebot/` unless explicitly prefixed with `.github/` or `projects/`:

src/voicebot/backend/; src/voicebot/contracts/sessions.py; tests/unit/backend/test_sessions.py; tests/integration/test_mock_session_api.py; fixtures/synthetic/backend/session_response.json; docs/w5.md

Do not edit another workstream or add dependencies unless this issue owns initial tooling. Report interface problems to Hemanth instead of introducing duplicate schemas.

## Steps

1. Implement in-memory session repository, states and documented transitions; request/correlation-ID middleware; typed HTTP response models and safe error handlers.
2. POST /api/sessions/mock calls W1 make_fake_pcm/chunk_pcm and W2 FakeTranscriber. Return audio metadata and transcript events with matching session/correlation IDs. Do not hardcode the transcript in the route.
3. Validate input and trace headers, normalize errors and avoid logging PCM/context. Health/readiness remain available.
4. Generate a deterministic session_response.json fixture by injecting fixed IDs/time into the same service used by the endpoint. Validate it with MockSessionResponse. Ruthwin consumes this exact file.
5. Add python -m voicebot.backend launcher defaulting to mock mode at 127.0.0.1:8000. Test the full real mock pipeline through FastAPI, missing sessions/invalid transitions, and malformed request errors.

## Checks to run

Python commands run from `projects/sde-1-voicebot`; npm commands from its `frontend` folder. Commands become available after the setup prerequisites and named test files exist. A server/demo command may keep running; stop it with Ctrl+C after checking it.

- `uv run pytest tests/unit/backend/test_sessions.py tests/integration/test_mock_session_api.py`
- `uv run python -m voicebot.backend`
- `uv run ruff check .`

## Definition of done

- [ ] Scope above implemented; exact shared names, fields and units preserved.
- [ ] Normal behavior and meaningful failure cases verified with real test output.
- [ ] Producer/consumer compatibility verified using the documented fixture or integration test where relevant.
- [ ] No credentials, real captures, recordings, personal data or unrelated code committed.
- [ ] PR opened against the team branch, linked to this issue, and reviewed; required checks pass.
- [ ] Contributor can explain the main input, output, and one failure case.
- [ ] Hemanth receives a factual daily report (work, files, tests, branch/PR, blocker, next step).

## Paste into your coding assistant

> Implement only this issue. Read the entire body and the repository guidance it names. Check the remote and branch before editing. Use the exact interfaces in docs/contracts.md and connection checks in docs/CONNECTIONS.md. Work only in allowed paths; do not build the entire project or replace other modules with your own code. Implement the listed steps and tests, run the checks, and report actual results. Explain the code in simple terms. Do not merge or access the original repository. If a prerequisite is missing, report the blocker; do not invent its output or claim integration passed.

## Requirement source

This is our implementation breakdown of the supplied official Week 1 task descriptions and execution plan (§§7–16). Daily scope and concrete interfaces are team decisions. No feature is complete just because this issue exists.
