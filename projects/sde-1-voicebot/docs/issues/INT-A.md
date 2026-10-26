# [INT-A] Connect the UI to the backend and prove the full mock path

Suggested owner: **Ruthwin**. Hemanth will assign the GitHub issue. Reviewer: **Hemanth**. Estimate: **3–5 focused hours**. Milestone: **Week 1 — Foundation**.

## Before starting

- Repository: `neonjava/acd_voicebot` only. Do not access the original repository.
- The structure PR must be merged into `team/sde-1-voicebot` before branching.
- Prerequisite issues (must be merged before final verification): **W5-B, W6-B**.
- Feature branch: `feature/int-a-implementation`; PR base: `team/sde-1-voicebot`.
- Read root AGENTS.md, team README.md, docs/START_HERE.md, docs/contracts.md and docs/CONNECTIONS.md. The interface specification is a concrete provisional team decision, not provider approval.
- This is initially a documentation/folder scaffold. W5-A creates Python tooling; W6-A creates frontend tooling. Do not assume files already exist.

## Goal

The required Week 1 path works: UI→backend→W1→W2→backend→UI, using actual module implementations and shared contract tests.

## Files you own for this issue

Paths below are relative to `projects/sde-1-voicebot/` unless explicitly prefixed with `.github/` or `projects/`:

frontend/; tests/integration/test_ui_fixture_contract.py; docs/demo.md; docs/w6.md

Do not edit another workstream or add dependencies unless this issue owns initial tooling. Report interface problems to Hemanth instead of introducing duplicate schemas.

## Steps

1. Replace the fixture client at the application composition point with HTTP startMockSession(). Keep fixture mode for unit tests. Configure Vite /api proxy to 127.0.0.1:8000.
2. Consume W5 session_response.json in frontend client tests. Add a Python contract test validating that same JSON with W5 MockSessionResponse. No duplicated drift-prone fixture.
3. Click Start and show the transcript coming from the running backend, which calls W1/W2. A frontend-only fixture is not proof of integration.
4. Document two-terminal setup, expected visible text, network failure/error recovery, and actual browser smoke evidence. Ask Hemanth to review the cross-module test.
5. Keep W3/W4 UI integration out of this required minimum issue.

## Checks to run

Python commands run from `projects/sde-1-voicebot`; npm commands from its `frontend` folder. Commands become available after the setup prerequisites and named test files exist. A server/demo command may keep running; stop it with Ctrl+C after checking it.

- `uv run pytest tests/integration/ (from team folder)`
- `npm test (from frontend)`
- `npm run build (from frontend)`
- `Manual: run backend and UI; start session; inspect transcript; stop backend and verify error state`

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
