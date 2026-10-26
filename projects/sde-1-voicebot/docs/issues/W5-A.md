# [W5-A] Set up Python tooling, shared envelopes, and health endpoints

Suggested owner: **Rakshita**. Hemanth will assign the GitHub issue. Reviewer: **Hemanth**. Estimate: **4–6 focused hours**. Milestone: **Week 1 — Foundation**.

## Before starting

- Repository: `neonjava/acd_voicebot` only. Do not access the original repository.
- The structure PR must be merged into `team/sde-1-voicebot` before branching.
- Prerequisite issues (must be merged before final verification): **Structure PR only**.
- Feature branch: `feature/w5-a-implementation`; PR base: `team/sde-1-voicebot`.
- Read root AGENTS.md, team README.md, docs/START_HERE.md, docs/contracts.md and docs/CONNECTIONS.md. The interface specification is a concrete provisional team decision, not provider approval.
- This is initially a documentation/folder scaffold. W5-A creates Python tooling; W6-A creates frontend tooling. Do not assume files already exist.

## Goal

A teammate can install the package, import voicebot.contracts.common, and run health/contract tests. This is the first technical dependency for W1–W4.

## Files you own for this issue

Paths below are relative to `projects/sde-1-voicebot/` unless explicitly prefixed with `.github/` or `projects/`:

pyproject.toml, uv.lock, .python-version; src/voicebot/__init__.py; package __init__.py files; src/voicebot/contracts/common.py; src/voicebot/backend/app.py; tests/contracts/test_common.py; tests/unit/backend/test_health.py; docs/w5.md

Do not edit another workstream or add dependencies unless this issue owns initial tooling. Report interface problems to Hemanth instead of introducing duplicate schemas.

## Steps

1. Initialize one Python 3.12 package with src layout (import voicebot). Use uv, FastAPI, Uvicorn, Pydantic v2, pytest, httpx, Ruff. Commit the generated lockfile; do not initialize another Git repository.
2. Implement the common primitives exactly as docs/contracts.md specifies: ContractModel forbids unknown fields; generic EventEnvelope[T], ErrorEnvelope, SessionState, WorkflowState. Domain-specific models belong to their owners.
3. Create FastAPI app and GET /api/health, GET /api/ready with documented mock JSON. Normalize validation/unexpected errors into ErrorEnvelope without leaking exceptions.
4. Publish a valid typed common-event example and test invalid payloads, missing fields, wrong version and non-UTC timestamps. Include successful/unavailable readiness tests.
5. Document setup commands and tell W1–W4 their shared import path is ready. Do not implement their models, session orchestration, or the frontend.

## Checks to run

Python commands run from `projects/sde-1-voicebot`; npm commands from its `frontend` folder. Commands become available after the setup prerequisites and named test files exist. A server/demo command may keep running; stop it with Ctrl+C after checking it.

- `uv sync --locked`
- `uv run pytest tests/contracts/test_common.py tests/unit/backend/test_health.py`
- `uv run ruff check .`
- `uv run ruff format --check .`

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
