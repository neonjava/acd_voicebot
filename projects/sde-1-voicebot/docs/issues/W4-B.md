# [W4-B] Build two harmless mock tools and enforce approvals

Suggested owner: **Shalini**. Hemanth will assign the GitHub issue. Reviewer: **Hemanth**. Estimate: **4–6 focused hours**. Milestone: **Week 1 — Foundation**.

## Before starting

- Repository: `neonjava/acd_voicebot` only. Do not access the original repository.
- The structure PR must be merged into `team/sde-1-voicebot` before branching.
- Prerequisite issues (must be merged before final verification): **W4-A**.
- Feature branch: `feature/w4-b-implementation`; PR base: `team/sde-1-voicebot`.
- Read root AGENTS.md, team README.md, docs/START_HERE.md, docs/contracts.md and docs/CONNECTIONS.md. The interface specification is a concrete provisional team decision, not provider approval.
- This is initially a documentation/folder scaffold. W5-A creates Python tooling; W6-A creates frontend tooling. Do not assume files already exist.

## Goal

An approved synthetic plan runs; pending/rejected plans provably execute no tools.

## Files you own for this issue

Paths below are relative to `projects/sde-1-voicebot/` unless explicitly prefixed with `.github/` or `projects/`:

src/voicebot/workflow/; tests/unit/workflow/test_executor.py; docs/w4.md

Do not edit another workstream or add dependencies unless this issue owns initial tooling. Report interface problems to Hemanth instead of introducing duplicate schemas.

## Steps

1. Implement only echo_text and mock_save_note as documented; both are in-memory simulations. Validate exact arguments and allow-list names.
2. Implement execute(plan, approvals=...) and preflight all approvals before any tool invocation. Match session+plan+step identities.
3. Missing approval waits; rejection cancels; consequential registry flags cannot be bypassed by a plan. Unknown tools fail safely. Terminal plans cannot execute.
4. Tests must use invocation counters/spies to prove zero tool calls for pending, rejected, mismatched or insufficient approvals. Test successful approved execution.
5. Add python -m voicebot.workflow.demo showing pending, approved, rejected results with synthetic plans. No network/shell/filesystem effects.

## Checks to run

Python commands run from `projects/sde-1-voicebot`; npm commands from its `frontend` folder. Commands become available after the setup prerequisites and named test files exist. A server/demo command may keep running; stop it with Ctrl+C after checking it.

- `uv run pytest tests/unit/workflow/test_executor.py`
- `uv run python -m voicebot.workflow.demo`
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
