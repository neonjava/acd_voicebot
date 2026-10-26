# Week 1 issue order

**No implementation is completed.** These are actionable assignments, left unassigned for Hemanth. Each member has A (foundation), B (working behavior), and C (expanded tests/demo). Two integration issues connect the work.

Start W5-A and W6-A first. W1–W4 can read their contracts immediately, then implement against the shared common models once W5-A merges. Do not wait until Day 7 to integrate.

| Issue | Suggested owner | Depends on |
|---|---|---|
| [[W5-A] Set up Python tooling, shared envelopes, and health endpoints](issues/W5-A.md) | Rakshita | Structure PR |
| [[W1-A] Define validated audio contracts that W2 will consume](issues/W1-A.md) | Hemanth | W5-A |
| [[W2-A] Define transcript contracts and a shared UI fixture](issues/W2-A.md) | Megha | W5-A |
| [[W3-A] Define synthetic context and reasoning contracts](issues/W3-A.md) | Saanvi | W5-A |
| [[W4-A] Define workflow contracts and legal state transitions](issues/W4-A.md) | Shalini | W5-A |
| [[W6-A] Initialize React tooling and accessible mock session controls](issues/W6-A.md) | Ruthwin | Structure PR |
| [[W1-B] Build deterministic fake PCM source, chunker and CLI](issues/W1-B.md) | Hemanth | W1-A |
| [[W2-B] Connect W1 audio to a fake transcriber and ordered accumulator](issues/W2-B.md) | Megha | W2-A, W1-B |
| [[W3-B] Build deterministic synthetic reasoning and versioned prompts](issues/W3-B.md) | Saanvi | W3-A |
| [[W4-B] Build two harmless mock tools and enforce approvals](issues/W4-B.md) | Shalini | W4-A |
| [[W5-B] Connect session API to actual W1 and W2 implementations](issues/W5-B.md) | Rakshita | W5-A, W1-B, W2-B |
| [[W6-B] Render transcript fixtures through a typed client and permission states](issues/W6-B.md) | Ruthwin | W6-A, W2-A |
| [[W1-C] Add failure/boundary tests and Week 1 demo evidence](issues/W1-C.md) | Hemanth | W1-B |
| [[W2-C] Add failure/boundary tests and Week 1 demo evidence](issues/W2-C.md) | Megha | W2-B |
| [[W3-C] Add failure/boundary tests and Week 1 demo evidence](issues/W3-C.md) | Saanvi | W3-B |
| [[W4-C] Add failure/boundary tests and Week 1 demo evidence](issues/W4-C.md) | Shalini | W4-B |
| [[W5-C] Add failure/boundary tests and Week 1 demo evidence](issues/W5-C.md) | Rakshita | W5-B |
| [[W6-C] Add failure/boundary tests and Week 1 demo evidence](issues/W6-C.md) | Ruthwin | W6-B |
| [[INT-A] Connect the UI to the backend and prove the full mock path](issues/INT-A.md) | Ruthwin | W5-B, W6-B |
| [[INT-B] Add CI and verify all six workstreams before the demo](issues/INT-B.md) | Hemanth | INT-A, W3-B, W4-B |

A/B feature PRs include basic tests. C is the separate test PR required weekly. Merge and demonstrated evidence are required before marking done.

Hemanth reviews coordination changes. No GitHub assignees are set automatically.
