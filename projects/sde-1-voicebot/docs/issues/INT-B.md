# [INT-B] Add CI and verify all six workstreams before the demo

Suggested owner: **Hemanth**. Hemanth will assign the GitHub issue. Reviewer: **Rakshita**. Estimate: **3–5 focused hours**. Milestone: **Week 1 — Foundation**.

## Before starting

- Repository: `neonjava/acd_voicebot` only. Do not access the original repository.
- The structure PR must be merged into `team/sde-1-voicebot` before branching.
- Prerequisite issues (must be merged before final verification): **INT-A, W3-B, W4-B**.
- Feature branch: `feature/int-b-tests`; PR base: `team/sde-1-voicebot`.
- Read root AGENTS.md, team README.md, docs/START_HERE.md, docs/contracts.md and docs/CONNECTIONS.md. The interface specification is a concrete provisional team decision, not provider approval.
- This is initially a documentation/folder scaffold. W5-A creates Python tooling; W6-A creates frontend tooling. Do not assume files already exist.

## Goal

CI checks the real modules and both required integration and optional reasoning/workflow composition have explicit evidence.

## Files you own for this issue

Paths below are relative to `projects/sde-1-voicebot/` unless explicitly prefixed with `.github/` or `projects/`:

.github/workflows/sde1-ci.yml; projects/sde-1-voicebot/tests/integration/test_reasoning_workflow_handoff.py; projects/sde-1-voicebot/docs/demo.md; projects/sde-1-voicebot/docs/architecture.md

Do not edit another workstream or add dependencies unless this issue owns initial tooling. Report interface problems to Hemanth instead of introducing duplicate schemas.

## Steps

1. Add path-aware CI for this team: locked Python install, Ruff lint/format, pytest including contracts/integration; npm ci, frontend tests and build. Workflow targets team-branch PRs. Do not change repository protection settings here.
2. Verify INT-A required connected path and collect each member’s actual production/test PR links. Designate an integration/QA coordinator with the team.
3. Add a small integration test mapping W2 TranscriptSegment to W3 ContextItem/ReasoningRequest using documented IDs; feed W3 answer as text to a W4 echo_text step with matching explicit approval. Use actual implementations. This is a mock composition test, not a production WorkflowProposal API or UI feature.
4. Verify source IDs survive the reasoning handoff and a rejected workflow approval produces zero tool invocations. Do not modify other owners’ modules without coordination.
5. Record clean setup instructions, commands/results and limitations. Do not claim Day 7 demo or all contributions complete until verified.

## Checks to run

Python commands run from `projects/sde-1-voicebot`; npm commands from its `frontend` folder. Commands become available after the setup prerequisites and named test files exist. A server/demo command may keep running; stop it with Ctrl+C after checking it.

- `uv sync --locked`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`
- `npm ci && npm test && npm run build (from frontend)`
- `Verify GitHub Actions results and manual INT-A demo`

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
