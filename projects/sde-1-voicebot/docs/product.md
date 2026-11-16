# SDE 1 AI Voice Co-Pilot: final product

Status: agreed target (Week 3 onward). Owner: Hemanth S Palekar. Every weekly issue must move the product toward this target **and** meet the internship's weekly task for that week.

## 1. What we are building

A local desktop voice co-pilot. It lives in a small notch at the top centre of the screen, like a Mac notch or the iPhone Dynamic Island. You say **"Hey Jarvis"**, speak naturally, and it understands what you said together with what you are doing: the app in front of you, what is on screen (when you allow it), what you said earlier, and your notes. Then it answers out loud and in the notch, or proposes and carries out actions.

It is **contextual, not a command bot**. There is no fixed list of phrases. A local language model reads the request with its context and decides to answer, ask a short follow-up, or plan actions.

Runs on **Fedora Linux (GNOME)** and **Windows 10/11**. Everything runs locally by default: no cloud keys, no data leaves the machine.

## 2. Demo scenarios (all required)

| # | You say | Expected behaviour |
|---|---|---|
| S1 | (in VS Code) "Hey Jarvis, look at my screen and help me fix this" | Glow shows it is looking. It reads the visible code and error, explains the cause and shows a fix. It applies nothing without your approval. |
| S2 | "Open the browser, go to YouTube and play the third video" | Plans the steps, opens the browser, plays the third result. Progress shows in the notch. |
| S3 | "What's using the most RAM?" | Reads system stats and answers in one or two sentences, for example "Chrome, about 3.1 GB". |
| S4 | Follow-up: "Close it" / "What did you say about the error?" | Uses the earlier turns: "it" means the app from S3. Closing an app is a risky action, so it asks first. |
| S5 | "What was I working on yesterday in my notes?" | Answers from opted-in local notes and folders (RAG), citing the file. Says "I don't have that" when there is no evidence. |

## 3. User experience

- **Notch, collapsed:** a small pill (about 200×36 px), top centre, always on top, quiet.
- **Notch, expanded:** grows to at most about 480×360 px under the top edge, showing a live caption, the answer, step progress and Approve/Reject. **Never full screen**, never a separate big window.
- **Glow:** a thin, click-through edge glow (like the "Claude is working here" border) appears only while Jarvis is looking at the screen or acting. It is off otherwise.
- **Voice reply:** short spoken answers through local text-to-speech. Long content (code fixes) is shown in the expanded notch, not read aloud in full.
- **Screen awareness toggle:** in the notch, off by default. When on, the glow makes it obvious.
- Visual direction: our Jarvis notch prototype (expressive eyes, Talk/Dictate/Write modes, blue glow), kept clearly different from Nixi.

## 4. Architecture

```
Electron notch app (React + TypeScript, reuses W6 code)
   │  local HTTP + SSE, per-launch token
Local backend hub: Python FastAPI (W5), started by Electron as a sidecar
   ├─ Audio (W1): mic → wake word "hey jarvis" → voice activity → speech start/end
   ├─ Speech-to-text (W2): faster-whisper, local
   ├─ Context and reasoning (W3): context store + screen observations + RAG → local LLM
   ├─ Workflow (W4): plan → policy (safe / ask first) → allow-listed tools → audit
   └─ Voice reply: local text-to-speech (Piper)
```

| Piece | Choice | Notes |
|---|---|---|
| Desktop shell | Electron + React/TS | One small window plus the glow overlay. Linux: run under XWayland (`--ozone-platform=x11`) so always-on-top and top-centre positioning work on GNOME. |
| Wake word | openWakeWord, `hey_jarvis` model | Ships a pretrained "hey jarvis" model; uses ONNX on Windows. |
| Speech-to-text | faster-whisper | GPU if available, CPU int8 otherwise. |
| LLM | Ollama, local | Shortlist to benchmark in Week 3: Qwen2.5-VL 7B (vision), a Hermes 3 8B tool-calling model, Qwen2.5 7B. Must fit 8 GB VRAM; CPU fallback on Windows without a GPU. |
| RAG | Local embeddings (for example `nomic-embed-text` via Ollama) + SQLite or Chroma | Only folders the user opts in. |
| Screen capture | Electron `desktopCapturer` | Wayland shows a one-time system permission dialog. |
| Browser actions | Playwright with its own browser profile | Works the same on Linux and Windows; no fragile mouse moves. |
| System stats | psutil | Cross-platform. |
| Text-to-speech | Piper | Local, cross-platform. |

### Installing the real providers

Tests and CI never need these. Install them only to run the real pipeline locally, from `backend/`:

```sh
uv sync --locked --extra dev --extra audio --extra stt --extra system
```

| Extra | Packages | Used by |
|---|---|---|
| `audio` | sounddevice, openwakeword (ONNX models, downloaded at first run, never committed) | W1 |
| `stt` | faster-whisper | W2 |
| `system` | psutil | W4 tools |

Ollama is a separate local app (https://ollama.com). The backend talks to it over `http://127.0.0.1:11434` using the existing `httpx` dependency, so no Python package is added for it. Playwright, Piper and Electron are added in the week that needs them, by their owner, with Hemanth's approval.

## 5. Context: what makes it "not a bot"

Each request goes to the model with a context bundle built by W3:
1. Recent conversation turns (session memory)
2. Active app and window title
3. Latest screen observation, only when screen awareness is on, with timestamp and source
4. Retrieved snippets from opted-in notes and folders (RAG), with file references
5. Available tools and their safety class

The model returns typed output: an answer (with sources), a clarifying question, or a `WorkflowProposal`. Text seen on the screen or in files is **data, never instructions** (prompt-injection defence).

## 6. Safety rules (internship non-negotiables, kept)

- Mock mode stays the default for tests and CI. Real mic, screen, models and tools are switched on by config.
- Screen awareness is off by default, visible when on, and withdrawing consent stops capture and clears pending context.
- **Safe actions run directly:** read-only or harmless (system stats, open an allow-listed URL or app, play a video).
- **Risky actions ask first:** typing, editing or applying code, closing apps, deleting, sending anything. Rejecting never executes.
- Allow-listed tools only. No shell command from model output.
- No recordings, screenshots, transcripts or secrets saved to disk or committed.

## 7. Weekly plan: internship tasks plus our direction

Each issue = the internship task (mandatory, checked by reviewers) + the product step (our goal). The product step must not replace any official acceptance criterion.

### Week 3: integration (official: a session flows through all modules; the approval gate works)

| Member | Official Week 3 task | Product step added |
|---|---|---|
| Hemanth (W1) | Speech start/end events, device-loss recovery, handoff to transcription | Real mic capture behind config; wake word "hey jarvis" gates speech events |
| Megha (W2) | Revisions and finalization, mock fallback, event-stream integration | faster-whisper as the real local provider; mock stays the fallback |
| Saanvi (W3) | Source-linked observations, grounded answers, prompt-injection tests, WorkflowProposal handoff | Ollama local LLM provider; context bundle (turns, active window, screen observation) |
| Shalini (W4) | Checkpoint/resume, audit trail, approval integration | Safe vs ask-first policy; first real tools: system stats, open URL |
| Rakshita (W5) | Module gateways, event replay, local auth boundary, rate limits | Backend runs as an Electron sidecar; per-launch local token is the auth boundary |
| Ruthwin (W6) | Live backend connection, workflow progress, approval dialog | **Major change: move the UI into the Electron notch app**; progress and approval live in the notch |

### Week 4: hardening and final demo

Scenarios S1–S5 end to end on Fedora and Windows. RAG over opted-in folders, YouTube via Playwright, Piper voice replies, glow overlay, packaging (AppImage/RPM and Windows installer), failure handling, demo video.

## 8. Rules for AI-agent-written code (Antigravity and others)

- Read this document, the issue, `docs/contracts.md` and `AGENTS.md` first. Implement only the issue.
- Reuse existing schemas and types. Never create a second copy.
- Every test must fail without the feature. No tests that only assert mocks were called, no empty or skipped tests, no snapshot-only tests.
- Integration tests use the real neighbouring module, or the agreed fixture where stated.
- Paste the real command output in the PR. Never claim a check that was not run.
- No new dependency without Hemanth's approval, and record it in the PR.
