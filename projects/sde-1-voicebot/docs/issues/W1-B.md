# [W1-B] Build deterministic fake PCM source, chunker and CLI

Suggested owner: **Hemanth**. Hemanth will assign the GitHub issue. Reviewer: **Megha**. Estimate: **3–5 focused hours**. Milestone: **Week 1 — Foundation**.

## Before starting

- Repository: `neonjava/acd_voicebot` only. Do not access the original repository.
- The structure PR must be merged into `team/sde-1-voicebot` before branching.
- Prerequisite issues (must be merged before final verification): **W1-A**.
- Feature branch: `feature/w1-b-implementation`; PR base: `team/sde-1-voicebot`.
- Read root AGENTS.md, team README.md, docs/START_HERE.md, docs/contracts.md and docs/CONNECTIONS.md. The interface specification is a concrete provisional team decision, not provider approval.
- This is initially a documentation/folder scaffold. W5-A creates Python tooling; W6-A creates frontend tooling. Do not assume files already exist.

## Goal

Two identical inputs produce identical AudioChunk lists and CLI metadata. W2 can call this implementation directly.

## Files you own for this issue

Paths below are relative to `projects/sde-1-voicebot/` unless explicitly prefixed with `.github/` or `projects/`:

src/voicebot/audio/; tests/unit/audio/test_chunker.py; docs/w1.md

Do not edit another workstream or add dependencies unless this issue owns initial tooling. Report interface problems to Hemanth instead of introducing duplicate schemas.

## Steps

1. Implement make_fake_pcm and chunk_pcm with the exact signatures in contracts.md. Import W1-A schemas.
2. Generate synthetic PCM entirely in memory. Derive offsets and sequence IDs from sample position; no clock, random output, devices, disk or paid APIs.
3. CLI prints chunk metadata, not raw PCM. Empty stream returns []; reject corrupt frame length and invalid chunk duration safely.
4. Test 1000ms→50 chunks, repeatability, contiguous offsets, increasing sequence IDs, shorter valid final chunk, and invalid input. Give Megha the exact import paths.

## Checks to run

Python commands run from `projects/sde-1-voicebot`; npm commands from its `frontend` folder. Commands become available after the setup prerequisites and named test files exist. A server/demo command may keep running; stop it with Ctrl+C after checking it.

- `uv run pytest tests/unit/audio/test_chunker.py`
- `uv run python -m voicebot.audio.cli`
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
