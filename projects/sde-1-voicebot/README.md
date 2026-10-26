# AcademiaAI SDE 1 — project structure and assignments

**Planning scaffold only. No application, contracts, dependency configuration, tests, or CI have been implemented.** Folder placeholders mark where each member will work. This is intentional: teammates implement their assigned issues themselves.

Repository: `neonjava/acd_voicebot`. Integration branch: `team/sde-1-voicebot`.

## Start here

1. Accept your GitHub collaborator invitation.
2. Read your assigned issue and [beginner guide](docs/START_HERE.md).
3. After the structure PR is merged, create a feature branch from the team branch.
4. Give your coding assistant the full issue and its prompt; implement that issue only.
5. Run actual checks, open a PR, and ask Hemanth to review it.

## Folder ownership

| Member | Workstream | Owned implementation | Owned contract file |
|---|---|---|---|
| Hemanth | W1 Audio | `src/voicebot/audio/` | `src/voicebot/contracts/audio.py` |
| Megha | W2 STT | `src/voicebot/transcription/` | `src/voicebot/contracts/transcription.py` |
| Saanvi | W3 Reasoning | `src/voicebot/reasoning/` | `src/voicebot/contracts/reasoning.py` |
| Shalini | W4 Workflow | `src/voicebot/workflow/` | `src/voicebot/contracts/workflow.py` |
| Rakshita | W5 Backend | `src/voicebot/backend/` | `src/voicebot/contracts/common.py`, `sessions.py` |
| Ruthwin | W6 Frontend | `frontend/` | frontend types following the shared wire contract |

Owners also maintain matching test folders, synthetic fixtures, and workstream docs. Hemanth coordinates integration; no other QA coordinator has been assigned automatically.

## Planned commands — available only after setup issues merge

W5-A creates Python packaging/dependencies and common primitives. From this folder:

```sh
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

W6-A creates frontend tooling. From `frontend/`:

```sh
npm ci
npm test
npm run build
npm run dev
```

Install Git, uv, and Node 22.22.2. W5-A uses Python 3.12, managed by uv. Lockfile generation belongs to the setup owners. These commands have NOT been verified against a completed project; there is no runnable code in this scaffold.

## Read next

- [Beginner Git and AI-assistant guide](docs/START_HERE.md)
- [Concrete shared interfaces](docs/contracts.md)
- [Week 1 issue order](docs/WEEK1_BACKLOG.md)
- [Architecture and integration checkpoints](docs/architecture.md)

## Decisions and source of truth

Official requirements: supplied execution-plan PDF, version 1.0, 24 October 2026, §§7–16, and six Week 1 task screenshots. They require working module code, tests, reviewed PRs and a mock session displayed in the UI by Day 7. Every member needs a production-code PR and a separate test PR with evidence.

Team proposals: Python 3.12/FastAPI/Uvicorn/Pydantic v2, uv/pytest/Ruff, React/TypeScript/Vite/Vitest/Testing Library, and the precise interfaces in contracts.md. Provider approval of stack/platform is not claimed. Tailwind and real providers are deferred. Week 1 uses synthetic data, in-memory sessions, and no paid APIs or real capture.

Hemanth selected private standalone development here. Do not access the original repository unless he explicitly authorizes it later. Making this repository public later will not restore its fork relationship; upstream submission will require a new fork and branch transfer preserving commit history.
