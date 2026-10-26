# Week 1 architecture

One Python process owns backend orchestration and imports audio, transcription, reasoning, and workflow modules. React talks to it over HTTP. No service-per-workstream architecture.

Required connected path: start → in-memory session → W1 synthetic PCM/chunks → W2 fake transcription → typed response → W6 transcript display. W3 and W4 independently run and pass tests this week; connecting them to the UI is stretch work after the minimum path works.

Day 1–2: contracts and shells. Day 3: W1→W2 test. Day 4: backend uses the actual mocks and frontend consumes its response. Day 5: end-to-end smoke demo. Day 6: negative tests, clean setup, fixes and reviews. Day 7: reviewed merges, six module demos, evidence and limitations. These are relative days, not invented deadlines.

Hemanth coordinates interfaces and integration. No additional QA coordinator is assigned automatically; Hemanth should designate one. CI is a separate integration issue; no workflow is implemented yet. Each member owns their tests and reviews one peer PR daily under the official cadence.

## Integration checks

- Actual W1/W2 implementations are called, not a transcript hardcoded into the API/UI.
- IDs and timestamp units agree across boundaries.
- Mock session runs without credentials, devices, real providers, or stored recordings.
- Invalid input produces a safe traceable error and the UI recovers visibly.
- Unit, contract and integration checks run; browser smoke steps are recorded honestly.
- Every member has production and expanded-test PR evidence.
- Unimplemented features remain documented as such.

Shared-root AGENTS.md and README are coordinator setup work; future CI is an explicit integration issue in this user-owned repository. Future work stays in the team folder unless an issue explicitly allows otherwise.
