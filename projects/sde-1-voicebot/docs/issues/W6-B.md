# [W6-B] Render transcript fixtures through a typed client and permission states

Suggested owner: **Ruthwin**. Hemanth will assign the GitHub issue. Reviewer: **Hemanth**. Estimate: **4–6 focused hours**. Milestone: **Week 1 — Foundation**.

## Before starting

- Repository: `neonjava/acd_voicebot` only. Do not access the original repository.
- The structure PR must be merged into `team/sde-1-voicebot` before branching.
- Prerequisite issues (must be merged before final verification): **W6-A, W2-A**.
- Feature branch: `feature/w6-b-implementation`; PR base: `team/sde-1-voicebot`.
- Read root AGENTS.md, team README.md, docs/START_HERE.md, docs/contracts.md and docs/CONNECTIONS.md. The interface specification is a concrete provisional team decision, not provider approval.
- This is initially a documentation/folder scaffold. W5-A creates Python tooling; W6-A creates frontend tooling. Do not assume files already exist.

## Goal

W2’s canonical fixture renders correctly and a typed client boundary is ready for W5’s endpoint.

## Files you own for this issue

Paths below are relative to `projects/sde-1-voicebot/` unless explicitly prefixed with `.github/` or `projects/`:

frontend/; docs/w6.md

Do not edit another workstream or add dependencies unless this issue owns initial tooling. Report interface problems to Hemanth instead of introducing duplicate schemas.

## Steps

1. Add typed API representations following contracts.md, a client interface startMockSession(), fixture implementation and runtime response validation. Do not invent differently named fields.
2. Read fixtures/synthetic/transcription/final_event.json from W2 in tests (configure JSON imports or use fs in tests). Render a timeline with ordered text, times and interim/final status.
3. Show simulated permission states prompt/granted/denied/unavailable, labelled mock. Never call getUserMedia.
4. Add loading/error states, accessible status announcements and ignore late results after stop. Keep client injection so integration can switch to HTTP without rewriting components.
5. Tests cover fixture rendering, ordering, denied permission, error display and stop-before-response. No W3/W4 pages in this issue.

## Checks to run

Python commands run from `projects/sde-1-voicebot`; npm commands from its `frontend` folder. Commands become available after the setup prerequisites and named test files exist. A server/demo command may keep running; stop it with Ctrl+C after checking it.

- `npm test -- src/transcript.test.tsx`
- `npm run build`

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
