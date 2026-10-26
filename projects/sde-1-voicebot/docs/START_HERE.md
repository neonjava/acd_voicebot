# One issue at a time

An issue is your assignment. A branch holds your changes separately. A commit saves reviewed changes. A pull request (PR) asks the team to review and combine them; opening a PR does not merge it.

## Prepare once

Install [Git](https://git-scm.com/downloads), [uv](https://docs.astral.sh/uv/getting-started/installation/), and Node 22.22.2. Use your own GitHub account. Never paste credentials into an AI chat.

```sh
git clone https://github.com/neonjava/acd_voicebot.git
cd acd_voicebot
git remote -v
git config user.name
git config user.email
```

The remote must be neonjava/acd_voicebot. If your identity is missing, set your own name and verified/noreply GitHub email. Never copy another contributor's identity.

## Start an assignment

After Hemanth merges the foundation PR:

```sh
git status
git switch team/sde-1-voicebot
git pull --ff-only origin team/sde-1-voicebot
git switch -c feature/REPLACE-WITH-BRANCH-IN-ISSUE
```

If there are uncommitted changes or a command fails, show Hemanth the output. Do not reset, clean, force-push, or overwrite files to remove the error. The repository initially contains folders and documents only. W5-A creates Python tooling; W6-A creates frontend tooling. Run the planned README commands after those prerequisites exist. A focused test command works after you create its test file.

## Prompt for Antigravity or another coding assistant

> Implement only my assigned issue: ISSUE_URL. Read root AGENTS.md, projects/sde-1-voicebot/README.md, docs/contracts.md, and the complete issue. Confirm the repository is neonjava/acd_voicebot and your feature branch is based on team/sde-1-voicebot. Respect allowed files and dependencies. Use the assigned folders; initialize tooling only if your issue explicitly owns it. Do not generate a replacement application. Follow the exact interfaces, implement the checklist and meaningful tests, run the listed commands, and report actual results. Explain the input, output, and failure behavior to me. Do not merge, access the original repository, add real providers, or mark unfinished work done. Report missing dependencies rather than duplicating another person's code.

If the assistant cannot read the private issue, paste its entire body, not just the title.

## Submit your work

1. Read the diff. Ask your assistant to explain each changed file.
2. Run focused tests and the relevant full checks from the README.
3. From the repository root, run `git status`, `git diff --check`, and `git diff`.
4. Add only reviewed paths using `git add path/to/file`. Commit with a clear message.
5. Push: `git push -u origin YOUR-FEATURE-BRANCH`.
6. Open a PR in neonjava/acd_voicebot, base `team/sde-1-voicebot`, compare your feature branch. Include `Closes #ISSUE_NUMBER`, commands/results, and your explanation.
7. Request Hemanth's review. Do not merge your own PR. Address feedback on the same branch.
8. Send Hemanth your daily update for ClickUp.

If using GitHub CLI, always specify the repository and base:

```sh
gh pr create --repo neonjava/acd_voicebot --base team/sde-1-voicebot --head YOUR-FEATURE-BRANCH
```

## Daily report

- Completed work:
- Files changed:
- Test command and result:
- Branch / PR:
- Blocker:
- Next step:

Report facts only. The official plan requires a production-code PR and a separate test PR each week. Include basic tests with features; the third issue expands boundary/failure coverage and demo evidence.
