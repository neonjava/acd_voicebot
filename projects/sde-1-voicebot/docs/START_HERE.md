# Start your weekly assignment

An issue is your task list. A branch holds your changes. A PR asks Hemanth to review and combine them.

## 1. Get the project

Accept your collaborator invitation, install Git and uv (Python) or Node/npm (frontend), then:

```sh
git clone https://github.com/neonjava/acd_voicebot.git
cd acd_voicebot
git switch team/sde-1-voicebot
git pull --ff-only origin team/sde-1-voicebot
git switch -c feature/YOUR-BRANCH-FROM-THE-ISSUE
```

Use your own Git identity. If you already cloned, check `git status` first; do not overwrite existing changes. All work goes under `projects/sde-1-voicebot/`, except Rakshita's explicitly assigned CI workflow.

## 2. Give your coding assistant this

> Implement my assigned weekly issue: ISSUE_URL. Read its full description, root AGENTS.md, projects/sde-1-voicebot/README.md and docs/contracts.md. Use my assigned branch and folders. Implement only my workstream, not the whole project. Use the exact shared model names and interfaces. Publish contracts and a mock early so teammates can connect. Do not duplicate another person's models or silently change interfaces. Run meaningful tests and report actual results. Explain the code simply. Do not merge, push to shared branches or access the original repository. Report missing dependencies to Hemanth.

If the assistant cannot open a private issue, paste the entire issue body. Your folder starts empty; this is intentional. Rakshita creates Python tooling/common models first; Ruthwin creates frontend tooling. Follow the issue's checklist in order.

## 3. Connect early

After a prerequisite PR merges, with your working tree clean:

```sh
git fetch origin
git merge origin/team/sde-1-voicebot
```

Stay on your own feature branch. If conflicts appear, ask Hemanth before changing another person's files. Do not force-push. Compare examples with your consumer and run the assigned cross-module test before Friday afternoon.

## 4. Send for review

Run the issue's checks. Review `git status`, `git diff --check`, and `git diff`. Add only reviewed files, commit with your own identity and push your feature branch. Open a PR explicitly in neonjava/acd_voicebot against `team/sde-1-voicebot`; write `Related to #YOUR_ISSUE` and include real test output. Hemanth reviews/merges.

Do not wait until Friday to open a PR. Small early PRs for shared contracts unblock others. The official weekly production PR and separate test PR can both reference your single issue. For a follow-up PR after a merge, create a fresh branch from the updated team branch, e.g. `feature/w1-audio-tests`. Keep the weekly issue open until all its checkboxes are verified; do not use automatic closing keywords on partial PRs.

## 5. Daily update to Hemanth

Send: completed work, files changed, test command/result, branch/PR link, blocker, next step. Hemanth handles ClickUp. Never claim a test or demo happened when it did not.
