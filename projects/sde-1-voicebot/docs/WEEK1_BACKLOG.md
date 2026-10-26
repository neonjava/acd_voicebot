# Week 1 issue order

**Planning only: no implementation is completed.** All GitHub issues are unassigned for Hemanth. [Review and merge the structure PR #1](https://github.com/neonjava/acd_voicebot/pull/1) before feature branches start.

Start **W5-A (#2)** and **W6-A (#7)** first. W1–W4 read their contracts immediately and build against common models after W5-A merges. Each member works A → B → C. The B issues connect modules early; C expands test coverage.

| Issue | Suggested owner | Prerequisites |
|---|---|---|
| [[W5-A] Set up Python tooling, shared envelopes, and health endpoints #2](https://github.com/neonjava/acd_voicebot/issues/2) | Rakshita | Structure PR #1 |
| [[W1-A] Define validated audio contracts that W2 will consume #3](https://github.com/neonjava/acd_voicebot/issues/3) | Hemanth | [W5-A #2](https://github.com/neonjava/acd_voicebot/issues/2) |
| [[W2-A] Define transcript contracts and a shared UI fixture #4](https://github.com/neonjava/acd_voicebot/issues/4) | Megha | [W5-A #2](https://github.com/neonjava/acd_voicebot/issues/2) |
| [[W3-A] Define synthetic context and reasoning contracts #5](https://github.com/neonjava/acd_voicebot/issues/5) | Saanvi | [W5-A #2](https://github.com/neonjava/acd_voicebot/issues/2) |
| [[W4-A] Define workflow contracts and legal state transitions #6](https://github.com/neonjava/acd_voicebot/issues/6) | Shalini | [W5-A #2](https://github.com/neonjava/acd_voicebot/issues/2) |
| [[W6-A] Initialize React tooling and accessible mock session controls #7](https://github.com/neonjava/acd_voicebot/issues/7) | Ruthwin | Structure PR #1 |
| [[W1-B] Build deterministic fake PCM source, chunker and CLI #8](https://github.com/neonjava/acd_voicebot/issues/8) | Hemanth | [W1-A #3](https://github.com/neonjava/acd_voicebot/issues/3) |
| [[W2-B] Connect W1 audio to a fake transcriber and ordered accumulator #9](https://github.com/neonjava/acd_voicebot/issues/9) | Megha | [W2-A #4](https://github.com/neonjava/acd_voicebot/issues/4), [W1-B #8](https://github.com/neonjava/acd_voicebot/issues/8) |
| [[W3-B] Build deterministic synthetic reasoning and versioned prompts #10](https://github.com/neonjava/acd_voicebot/issues/10) | Saanvi | [W3-A #5](https://github.com/neonjava/acd_voicebot/issues/5) |
| [[W4-B] Build two harmless mock tools and enforce approvals #11](https://github.com/neonjava/acd_voicebot/issues/11) | Shalini | [W4-A #6](https://github.com/neonjava/acd_voicebot/issues/6) |
| [[W5-B] Connect session API to actual W1 and W2 implementations #12](https://github.com/neonjava/acd_voicebot/issues/12) | Rakshita | [W5-A #2](https://github.com/neonjava/acd_voicebot/issues/2), [W1-B #8](https://github.com/neonjava/acd_voicebot/issues/8), [W2-B #9](https://github.com/neonjava/acd_voicebot/issues/9) |
| [[W6-B] Render transcript fixtures through a typed client and permission states #13](https://github.com/neonjava/acd_voicebot/issues/13) | Ruthwin | [W6-A #7](https://github.com/neonjava/acd_voicebot/issues/7), [W2-A #4](https://github.com/neonjava/acd_voicebot/issues/4) |
| [[W1-C] Add failure/boundary tests and Week 1 demo evidence #14](https://github.com/neonjava/acd_voicebot/issues/14) | Hemanth | [W1-B #8](https://github.com/neonjava/acd_voicebot/issues/8) |
| [[W2-C] Add failure/boundary tests and Week 1 demo evidence #15](https://github.com/neonjava/acd_voicebot/issues/15) | Megha | [W2-B #9](https://github.com/neonjava/acd_voicebot/issues/9) |
| [[W3-C] Add failure/boundary tests and Week 1 demo evidence #16](https://github.com/neonjava/acd_voicebot/issues/16) | Saanvi | [W3-B #10](https://github.com/neonjava/acd_voicebot/issues/10) |
| [[W4-C] Add failure/boundary tests and Week 1 demo evidence #17](https://github.com/neonjava/acd_voicebot/issues/17) | Shalini | [W4-B #11](https://github.com/neonjava/acd_voicebot/issues/11) |
| [[W5-C] Add failure/boundary tests and Week 1 demo evidence #18](https://github.com/neonjava/acd_voicebot/issues/18) | Rakshita | [W5-B #12](https://github.com/neonjava/acd_voicebot/issues/12) |
| [[W6-C] Add failure/boundary tests and Week 1 demo evidence #19](https://github.com/neonjava/acd_voicebot/issues/19) | Ruthwin | [W6-B #13](https://github.com/neonjava/acd_voicebot/issues/13) |
| [[INT-A] Connect the UI to the backend and prove the full mock path #20](https://github.com/neonjava/acd_voicebot/issues/20) | Ruthwin | [W5-B #12](https://github.com/neonjava/acd_voicebot/issues/12), [W6-B #13](https://github.com/neonjava/acd_voicebot/issues/13) |
| [[INT-B] Add CI and verify all six workstreams before the demo #21](https://github.com/neonjava/acd_voicebot/issues/21) | Hemanth | [INT-A #20](https://github.com/neonjava/acd_voicebot/issues/20), [W3-B #10](https://github.com/neonjava/acd_voicebot/issues/10), [W4-B #11](https://github.com/neonjava/acd_voicebot/issues/11) |

Each issue contains allowed files, concrete steps, commands, acceptance criteria, reviewer, and a coding-assistant prompt. [Local issue drafts](issues/) remain readable offline; GitHub issues carry live dependency links.

A/B feature PRs include basic tests. C is the separate test PR required weekly. Reviewed merges and demonstrated evidence are required before marking done. The [connection map](CONNECTIONS.md) defines cross-module tests and Day 3–5 integration gates.
