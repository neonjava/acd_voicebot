# Connection map and acceptance gates

These are enforceable interface agreements and test assignments, not a claim that unimplemented modules already integrate. Every domain imports canonical contracts; no parallel schema definitions.

| Producer → consumer | Exact connection | Proof / owner |
|---|---|---|
| W5 foundation → W1–W4 | `voicebot.contracts.common` primitives | W5-A common contract tests; dependent schema imports |
| W1 → W2 | `make_fake_pcm` → `chunk_pcm` → `AudioChunk` → `FakeTranscriber.transcribe` | W2-B `test_audio_to_transcript.py` calls actual implementations |
| W2 → W5 | `TranscriptEvent` with `TranscriptSegment`/error payload | W5-B imports W2 provider and validates typed HTTP output |
| W5 → W6 | POST `/api/sessions/mock` → `MockSessionResponse` | Shared `fixtures/synthetic/backend/session_response.json`, Python contract test and TS client tests in INT-A |
| W2 → W6 early development | canonical `final_event.json` fixture | W6-B reads W2 fixture rather than inventing its own JSON shape |
| W2 → W3 | final segment → ContextItem with matching source/segment ID | INT-B real-module handoff test |
| W3 → W4 | validated answer text → allow-listed echo_text step + explicit matching approval | INT-B actual executor test; rejection must invoke zero tools |

## Handoff checklist for each PR

1. Name the consumer in the PR and link its dependent issue.
2. Import shared models; preserve exact field names and timing units in contracts.md.
3. Publish the documented synthetic fixture where the consumer expects it.
4. Run the cross-module test as soon as both producers are merged. A mocked substitute is unit evidence only.
5. If the consumer needs a contract change, coordinate and update specification, producer, consumer and fixture together. Do not silently rename fields.

## IDs, clocks and payload rules

- Audio sequence starts at zero. Media times are integer milliseconds from the audio origin.
- UTC event timestamps are separate, timezone-aware fields.
- The backend creates session/correlation IDs. All audio/transcript events in its response share them.
- Raw PCM stays between W1/W2. HTTP audio events contain metadata only.
- Transcript IDs remain stable through accumulation; final updates replace interim segments.
- Unknown schema version, mismatched session, or malformed payload is an error, not a silently accepted event.
- Error responses retain a safe correlation ID; UI displays safe messages, not exception dumps.

## Synthetic reference event for W2-A to create

```json
{
  "event_id": "event-transcript-0",
  "event_type": "transcript.segment",
  "schema_version": "1.0",
  "session_id": "session-demo",
  "correlation_id": "correlation-demo",
  "timestamp": "2026-01-01T00:00:00Z",
  "producer": "transcription",
  "payload": {
    "segment_id": "session-demo-segment-0",
    "session_id": "session-demo",
    "sequence_id": 0,
    "start_ms": 0,
    "end_ms": 1000,
    "text": "Hello from the mock voicebot.",
    "confidence": 1.0,
    "language": "en",
    "is_final": true
  }
}
```

## Integration gates

- By Day 3: W1→W2 test produces a final segment from actual synthetic chunks.
- By Day 4: W5 endpoint invokes the real W1/W2 mocks; W6 can render their fixture.
- By Day 5: UI Start calls backend; returned transcript appears. Disconnect backend and verify a safe visible error.
- Day 6: contract/error tests and clean setup; W3/W4 composition test if their mocks are ready.
- Day 7: all six module deliverables, reviewed PRs, actual CI and demo evidence.

The required UI flow is W1→W2→W5→W6. W3/W4 standalone deliverables are mandatory; their full UI integration is stretch scope this week. INT-B's small composition test checks their future connection without inventing a Week 1 production WorkflowProposal API.
