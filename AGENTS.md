# Instructions for coding assistants

Work only with `neonjava/acd_voicebot`. Do not read, fetch, push to, or open PRs against the original provider repository unless Hemanth explicitly authorizes it later.

Before editing team code, read the assigned issue, `projects/sde-1-voicebot/README.md`, and `projects/sde-1-voicebot/docs/contracts.md` on `team/sde-1-voicebot`. Implement only the assigned issue. Never generate a replacement application.

- Team code belongs in `projects/sde-1-voicebot/`.
- Base team feature branches on `team/sde-1-voicebot`. Team feature PRs target that branch in `neonjava/acd_voicebot` explicitly. Repository-level documentation may be proposed in a separate PR to `main` when Hemanth requests it.
- No direct pushes to `main` or shared team branches, no force pushes, no autonomous merges.
- Use the contributor's existing Git identity. Do not impersonate another teammate.
- Keep to the issue's allowed files. Ask Hemanth before changing another workstream or dependency configuration.
- Shared contracts live once in `projects/sde-1-voicebot/backend/app/contracts/`. Frontend API types must follow the documented wire contract.
- Mock mode is the default. No real microphone/screen capture, external messages, paid APIs, or model downloads for Week 1.
- Never commit secrets, recordings, private screenshots, personal data, virtual environments, or `node_modules`.
- Run the issue's checks; report actual output and unavailable checks. Do not claim an unrun test passed.
- Add meaningful tests with production code. Each member has one weekly issue; a follow-up test PR under that same issue adds boundary/failure coverage.
- Explain changed code to the contributor: purpose, input, output, failure cases, and how to run it.
- An unavailable dependency means report a blocker, not duplicate its implementation or silently change the interface.
- Record scope changes in docs and coordinate them with consumers.

## Code Review Rules

- Flag changes that duplicate shared contracts or silently change the documented W1→W2→W5→W6 interfaces. Consumers and shared fixtures must agree on fields, IDs, timestamps, and error shapes.
- Flag claims of passing tests or connected behavior when the PR shows only fixtures, mocks standing in for unfinished modules, or checks that did not run. Missing W5 setup must be reported as a blocker.
- Flag real capture, external side effects, paid providers, or committed private data in Week 1 mock work. Agent tools must remain allow-listed and approval-gated as documented.

The official internship PDF and supplied task descriptions define deliverables. Concrete names, paths, formats, and commands in this repository are provisional team implementation decisions, not claims of provider approval.
