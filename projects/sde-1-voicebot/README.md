# SDE 1 — one project, six assignments

**Folders and documentation only. No application code has been generated.** Each person owns one weekly issue and works on their own branch. Hemanth assigns and reviews the work.

## Folder structure

```text
projects/sde-1-voicebot/
├── backend/
│   ├── app/
│   │   ├── audio/          # W1 — Hemanth
│   │   ├── transcription/  # W2 — Megha
│   │   ├── reasoning/      # W3 — Saanvi
│   │   ├── agent/          # W4 — Shalini
│   │   ├── sessions/       # W5 — Rakshita
│   │   └── contracts/      # shared models, one file per owner
│   ├── tests/             # all Python tests
│   └── pyproject.toml     # Rakshita creates this in her issue
├── frontend/              # W6 — Ruthwin
├── docs/
│   ├── START_HERE.md      # Git and coding-assistant instructions
│   └── contracts.md       # agreed inputs/outputs for everyone
└── README.md
```

## Assignments

| Member | One issue for all Week 1 work | Feature branch |
|---|---|---|
| Hemanth | [#3 Audio and mock microphone](https://github.com/neonjava/acd_voicebot/issues/3) | `feature/w1-audio` |
| Megha | [#4 Transcription](https://github.com/neonjava/acd_voicebot/issues/4) | `feature/w2-transcription` |
| Saanvi | [#5 Context and reasoning](https://github.com/neonjava/acd_voicebot/issues/5) | `feature/w3-reasoning` |
| Shalini | [#6 Agent workflow](https://github.com/neonjava/acd_voicebot/issues/6) | `feature/w4-agent` |
| Rakshita | [#2 Backend and sessions](https://github.com/neonjava/acd_voicebot/issues/2) | `feature/w5-backend` |
| Ruthwin | [#7 Frontend](https://github.com/neonjava/acd_voicebot/issues/7) | `feature/w6-frontend` |

All feature PRs target `team/sde-1-voicebot`. Never push directly to a shared branch. Separate folders prevent most editing conflicts; branches keep unfinished work separate. Use both.

## Finish before Saturday

The delayed Week 1 is compressed into the available time. Finish implementation, integration, tests and reviews by **Friday evening**. Saturday is for the demo, not first-time integration. This is a team deadline, not a claim that tomorrow-to-Saturday is seven calendar days.

| When | Everyone's checkpoint |
|---|---|
| Tomorrow morning | Rakshita publishes Python setup/common contracts in a small PR first. Everyone else starts their own contract or UI files in parallel; no copies of shared models. Hemanth reviews the early PR promptly. |
| Tomorrow afternoon | Domain contracts and example data are shared. Each member has a draft PR and basic tests. Ruthwin can render Megha's transcript fixture. |
| Next working day, before Friday | Working mocks. Megha tests actual Hemanth chunks; Rakshita calls both; Ruthwin starts connecting to the API. Saanvi/Shalini demonstrate their mocks separately. |
| Friday morning | Required full path works: UI Start → backend session → fake audio → fake transcript → visible UI transcript. Fix interface mismatches now. |
| Friday afternoon/evening | Failure tests, six module demos, CI, setup instructions, reviewed merges and evidence. No new optional features. |
| Saturday | Demonstrate already-tested work. |

## How the six parts connect

| Connection | Agreement | Who verifies it |
|---|---|---|
| W1 → W2 | `app.audio` produces `AudioChunk`; W2 imports that model | Megha's real audio-to-transcript integration test |
| W2 → W5 | `FakeTranscriber` returns typed `TranscriptEvent` objects | Rakshita's mock-session API test |
| W5 → W6 | POST `/api/sessions/mock` returns `MockSessionResponse` | Rakshita + Ruthwin use the same JSON fixture |
| W2 → W3 | segment ID/text become source-linked context | Saanvi's transcript-context test |
| W3 → W4 | validated answer text can enter an allow-listed mock tool plan | Shalini's handoff test when W3 is ready; never bypass approvals |

W3/W4 module deliverables are required this week. Their full UI integration is optional; never delay the required transcript demo for it. Hemanth coordinates integration; Rakshita owns CI/setup within her backend issue. Share a contract/mock early rather than waiting for a whole weekly issue to finish. If a teammate is late, use the documented synthetic fixture temporarily and report the blocker; final integration must call actual implementations.

## Planned commands (after setup is implemented)

From `backend/`: `uv sync --locked`, `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run python -m app`.

From `frontend/`: `npm ci`, `npm test`, `npm run build`, `npm run dev`.

These commands are implementation targets, not currently runnable or verified results. Use Python 3.12 and a documented Node version compatible with the chosen frontend tooling.

## Read only these before coding

1. Your GitHub issue.
2. [Getting started](docs/START_HERE.md).
3. [Shared interfaces](docs/contracts.md), especially your section and your consumer's.

Official requirements come from the supplied Week 1 tasks and execution-plan PDF (version 1.0, 24 October 2026). Folder layout, precise interfaces, stack and compressed deadline are team decisions; provider approval is not claimed. The official plan asks for a production-code PR and a separate test PR per member; both can belong to the same weekly issue. Keep that issue open until everything is verified.

Work only in this private repository. Do not access the original provider repository without Hemanth's later instruction. No real capture, paid providers, recordings, private screenshots or secrets in Week 1.

## Pull request checks and Codex review

PRs targeting `team/sde-1-voicebot` run backend lint, formatting and pytest. Once W6 adds `frontend/package.json`, CI also runs frontend tests and build; `npm ci` requires a committed lockfile. Backend checks require W5's `pyproject.toml`, `uv.lock`, and shared contracts, so W1-only PRs will show a dependency failure until W5's setup merges.

A separate workflow posts `@codex review` once when a ready PR opens or a draft becomes ready. This comment is a request, not proof of review; confirm Codex reacts and posts its GitHub review. For reliable review on every PR, connect this repository to Codex and enable **Automatic review** in [Codex code review settings](https://chatgpt.com/settings/code-review). The repository owner must configure that account setting. CI checks remain required even when Codex reviews a PR.
