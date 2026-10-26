# Instructions for coding assistants

Work only with `neonjava/acd_voicebot`. Do not read, fetch, push to, or open PRs against the original provider repository unless Hemanth explicitly authorizes it later.

Read the assigned issue, `projects/sde-1-voicebot/README.md`, and `docs/contracts.md` before editing. Implement only that issue. Never generate a replacement application.

- Team code belongs in `projects/sde-1-voicebot/`.
- Base feature branches on `team/sde-1-voicebot`. PRs target that branch in `neonjava/acd_voicebot` explicitly.
- No direct pushes to main or shared team branches, no force pushes, no autonomous merges.
- Use the contributor's existing Git identity. Do not impersonate another teammate.
- Keep to the issue's allowed files. Ask Hemanth before changing another workstream or dependency configuration.
- Shared contracts live once in `src/voicebot/contracts/`. Frontend API types must follow the documented wire contract.
- Mock mode is the default. No real microphone/screen capture, external messages, paid APIs, or model downloads for Week 1.
- Never commit secrets, recordings, private screenshots, personal data, virtual environments, or node_modules.
- Run the issue's checks; report actual output and any unavailable checks. Do not claim an unrun test passed.
- Add meaningful tests with production code. The later test issue adds boundary/failure coverage.
- Explain the changed code to the contributor: purpose, input, output, failure cases, and how to run it.
- An unavailable dependency means report a blocker, not duplicate its implementation or silently change the interface.
- Scope changes must be recorded in docs and coordinated with consumers.

The official internship PDF and supplied task descriptions define deliverables. The concrete names, paths, formats, and commands in this repository are provisional team implementation decisions, not claims of provider approval.
