# Week 1 interfaces — provisional team baseline v1

These concrete interfaces are team decisions to unblock beginners. Official model names, common envelope fields and state names come from the assignments. Change an interface only after coordinating with Hemanth and its consumer. Models inherit Pydantic v2 `ContractModel`; definitions live only in `src/voicebot/contracts/`.

## Common conventions (to implement in W5-A)

W5-A must create `common.py` defining `ContractModel`, `EventEnvelope[T]`, `ErrorEnvelope`, `SessionState`, and `WorkflowState`.

- Event fields: event_id, event_type, schema_version (literal "1.0"), session_id, correlation_id, timestamp, producer, payload.
- Envelope timestamp: UTC ISO-8601 with timezone. Media positions: integer milliseconds from session audio start. Never mix the two.
- IDs: nonempty strings. Backend creates session/correlation IDs; producers create event IDs. Tests supply fixed IDs and UTC clock. No sleeps or wall-clock-dependent mock output.
- Error fields: code, message_safe_for_user, retryable, correlation_id, details_redacted (safe string map). Never include credentials, raw exception text, recordings, or private context.
- Session states: created, active, paused, stopping, completed, failed, expired.
- Workflow states: draft, awaiting_approval, running, paused, succeeded, failed, cancelled.
- Reject unknown fields and incompatible schema versions. Typed payloads must validate; don't use arbitrary dictionaries everywhere.
- Domain constructors may raise Pydantic ValidationError. Boundary adapters normalize errors. An AudioError data model is not an Exception to raise directly.
- Require strict integers for counters/timing: booleans and fractional values are not valid counts.

## W1 → W2: audio

`contracts/audio.py`:

- `AudioFormat`: sample_rate_hz=16000, channels=1, encoding="pcm_s16le" (literal values for Week 1). Reject unsupported formats; no silent resampling.
- `AudioChunk`: session_id (nonempty), sequence_id (int >=0), start_ms (int >=0), duration_ms (int >0), format (AudioFormat), pcm (bytes, nonempty). Validate `len(pcm) == duration_ms * 16 * 2` for this fixed format.
- `AudioError`: extends ErrorEnvelope; code starts with "AUDIO_".

PCM is internal Python data. The UI receives metadata, not raw PCM bytes.

`audio/source.py`: `make_fake_pcm(*, duration_ms: int = 1000) -> bytes` returns repeatable synthetic PCM (no devices, files, network or randomness).

`audio/chunker.py`: `chunk_pcm(pcm: bytes, *, session_id: str, chunk_ms: int = 20) -> list[AudioChunk]`. Start sequence at zero; derive offsets from sample position. Empty input returns []; reject invalid chunk sizes, incomplete sample frames, and trailing audio not expressible in whole milliseconds. A shorter final whole-ms chunk is allowed. 1000ms at 20ms yields 50 chunks.

`audio/cli.py`: `uv run python -m voicebot.audio.cli` prints sequence, offset, duration, format and byte count only. Normalize invalid input to AudioError at this boundary with a demo correlation ID.

## W2 → W5/W6: transcripts

`contracts/transcription.py`:

- `TranscriptSegment`: segment_id/session_id (nonempty), sequence_id (int >=0), start_ms/end_ms (ints >=0, end >= start), text (nonblank), confidence (finite float 0..1 or null when unknown), language (nonempty tag, default "en"), is_final (bool).
- `TranscriptEvent`: typed envelope for event_type="transcript.segment" with TranscriptSegment or "transcript.error" with ErrorEnvelope; producer="transcription". Validate type/payload pairing, matching session IDs, and matching correlation IDs for error payloads.

`transcription/adapter.py`: provider-neutral Protocol with `transcribe(chunks: Sequence[AudioChunk], *, session_id: str, correlation_id: str, timestamp: datetime) -> list[TranscriptEvent]`, `health() -> str`, and `cancel(session_id: str) -> None`. Fake provider constructor accepts positive timeout_seconds. Real timeout/retry machinery is later-week work; cancellation prevents subsequent output for that session.

`transcription/mock.py`: `FakeTranscriber` implements the protocol. Nonempty valid input produces one final segment: text="Hello from the mock voicebot.", confidence=1.0, language="en", start/end covering input chunks. IDs derive from the supplied session and segment index. Empty input produces []; invalid ordering/mixed sessions produce a safe transcript.error event. The mock does not perform speech recognition. health() returns "ready".

`transcription/accumulator.py`: `SegmentAccumulator.add(event: TranscriptEvent) -> None`; `segments() -> list[TranscriptSegment]`. Order by start_ms, sequence_id, segment_id. Same segment ID replaces interim with final; repeats do not duplicate; final cannot regress to interim. Reject mixed sessions in one accumulator. Error events do not become transcript segments.

## W3: synthetic context and reasoning

`contracts/reasoning.py`:

- `SourceReference`: source_id, locator (nonempty synthetic label), kind ("synthetic_screen" or "transcript").
- `ContextItem`: item_id, text (nonblank), source (SourceReference).
- `ScreenContext`: frame_id, captured_at (UTC aware), capture_enabled (bool, default false), items (list[ContextItem]). Synthetic fixture items can exist with real capture disabled; the flag is permission for actual capture.
- `ReasoningRequest`: request_id, session_id, question (nonblank), context (list[ContextItem], default []), prompt_version (literal "v1").
- `ReasoningResult`: request_id, session_id, answer (nonblank), source_ids (list[str]), insufficient_evidence (bool), prompt_version="v1".

IDs are nonempty. `reasoning/mock.py`: `reason(request: ReasoningRequest) -> ReasoningResult`. Use fixed templates and supplied context only. No context gives an explicit insufficient-evidence answer and empty source_ids. Validate returned references against the request. Keep trusted instructions in `reasoning/prompts/v1.txt` separate from untrusted question/context. Never interpret context as tool instructions. `reasoning/demo.py` prints synthetic results. No screenshots or LLM calls.

## W4: safe mock workflow

`contracts/workflow.py`:

- `ToolSpec`: name, description (nonblank), consequential (bool).
- `WorkflowStep`: step_id, tool_name (nonempty), arguments (dict[str,str]), requires_approval (bool, default true).
- `WorkflowPlan`: plan_id, session_id, steps (nonempty list; unique step IDs), state (WorkflowState, default "draft").
- `ApprovalRequest`: approval_id, plan_id, step_id, session_id, status (pending/approved/rejected, default pending).
- `WorkflowResult`: plan_id, session_id, state (WorkflowState), outputs (dict[str,str], default {}), error (ErrorEnvelope or null).

All IDs nonempty. `workflow/state_machine.py`: `transition(current: WorkflowState, target: WorkflowState) -> WorkflowState`. Allowed: draft→awaiting_approval/running/cancelled; awaiting_approval→running/cancelled; running→paused/succeeded/failed/cancelled; paused→running/cancelled. Terminal states have no outgoing transitions. The executor separately enforces approval; transition validity is not authorization.

`workflow/tools.py`: exactly two allow-listed mocks: `echo_text({"text": ...})` returns text; `mock_save_note({"text": ...})` returns a simulated saved-note message without filesystem writes. Reject unknown tools and missing/extra arguments. mock_save_note is consequential for the demo.

`workflow/executor.py`: `execute(plan: WorkflowPlan, *, approvals: Sequence[ApprovalRequest] = ()) -> WorkflowResult`. An unapproved consequential step waits; a rejected approval cancels without invocation. Match approval session+plan+step, not a bare boolean. Registry consequential=true cannot be overridden by requires_approval=false. Preflight all approval requirements before running any step. If any is rejected/pending, execute zero tools and return cancelled/awaiting_approval. Each permitted step runs once per call. Reject executing plans already in terminal states. Durable resume/idempotency across separate calls are later work and must not be claimed.

No shell/browser/network tools, real file writes, generic eval, or actual external messages.

## W5 → W6: HTTP mock session

`backend/app.py` exports FastAPI `app`:

- GET `/api/health` → 200 {"status":"ok","mode":"mock"}.
- GET `/api/ready` → 200 {"status":"ready","mode":"mock"}; unavailable configuration → 503 ErrorEnvelope.
- POST `/api/sessions/mock`, body {} → 201 MockSessionResponse. Reject extra fields.
- `MockSessionResponse`: session_id, state="completed" for the completed finite run, mode="mock", events (typed audio metadata or TranscriptEvent envelopes).
- Audio event: event_type="audio.chunk", producer="audio", payload={sequence_id,start_ms,duration_ms,sample_rate_hz,channels,size_bytes}. No raw pcm. Envelope uses common fields. W5 owns `AudioChunkMetadata` (wire projection) in contracts/sessions.py; W1 owns AudioChunk (internal data).
- Order audio events before transcript events. Keep session/correlation IDs consistent.
- `X-Request-ID` unique per request; validate a supplied bounded `X-Correlation-ID` or generate one and return it. Provisional allowed correlation ID: 1–128 ASCII letters/digits/underscore/hyphen. Invalid supplied ID → safe 422 with a new valid correlation ID.
- API errors use ErrorEnvelope, including 422 validation errors and safe 500 failures. No stack traces or raw payloads in responses/logs.
- `backend/sessions.py`: in-memory repository and documented transition table. Minimum Week 1 path created→active→completed or failed. Define other permitted transitions and test illegal ones; full pause/resume endpoints are later work.
- Backend launch: `uv run python -m voicebot.backend`. Mock mode by default, bind 127.0.0.1:8000.

W5 integrates actual W1/W2 mocks after those PRs merge. Before that, an injected test service is allowed, but it is not end-to-end completion. Do not duplicate W1/W2 logic.

W6's client exposes `startMockSession(): Promise<MockSessionResponse>`. Keep fixture and HTTP implementations behind that interface. HTTP uses relative `/api/sessions/mock` (W6 must configure a Vite proxy to 127.0.0.1:8000). Validate responses at runtime rather than blindly casting JSON. Match documented shapes and share fixtures validated by Python integration tests; do not invent a competing schema. A generation approach can replace checked TS representations later by coordinated issue.

UI permission states are visibly simulated: prompt/granted/denied/unavailable. Do not call getUserMedia. Start/stop are local controls for the finite mock run; late results after stop must not update the UI. Backend lifecycle endpoints/streaming/replay are later-week work.
