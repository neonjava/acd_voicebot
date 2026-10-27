# Security policy

This repository is a private internship prototype. Week 1 uses deterministic mock data and is not a production voicebot.

## Reporting a vulnerability

Report a suspected vulnerability privately to repository owner [@neonjava](https://github.com/neonjava). If GitHub's **Report a vulnerability** option is available on this repository's Security tab, use it. Otherwise, contact Hemanth through the team's existing private channel. Do not put exploit details, credentials, recordings, screenshots, or personal data in an issue, PR, or public discussion.

Include the affected commit or branch, steps to reproduce using synthetic data, the expected and actual behavior, and the impact. Share only the minimum information needed to reproduce the problem. Hemanth will coordinate a fix with the owning workstream and update the reporter privately.

## Scope

The active team branch is `team/sde-1-voicebot`. This prototype has no production deployment or security support guarantee. Do not test against systems, accounts, devices, or data you do not own or have permission to use.

Never commit API keys, passwords, tokens, recordings, personal data, or private screenshots. If a secret is exposed, notify Hemanth privately and revoke or rotate it immediately; deleting a Git commit alone does not make the secret safe.
