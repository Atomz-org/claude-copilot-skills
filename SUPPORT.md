# Support

## How to get help

Ask questions and report problems through GitHub issues on
[Atomz-org/claude-copilot-skills](https://github.com/Atomz-org/claude-copilot-skills/issues),
using the existing issue templates (bug report or feature request).

Before filing an issue:

- Read [docs/START_HERE.md](docs/START_HERE.md) for orientation — what the
  repository contains and how the pieces fit together.
- If a check or gate is failing, read [docs/DEBUGGING.md](docs/DEBUGGING.md)
  first. `./scripts/check.sh` runs the same gates locally that pull requests
  run, and `python -m pytest -q` runs the test suite.
- Search existing issues; a report that already exists is better extended than
  duplicated.

A good issue states what you ran, what happened, and what you expected — the
templates prompt for exactly this.

## Issues versus security reports

A suspected security vulnerability never goes in a public issue. Follow
[SECURITY.md](SECURITY.md) instead, which describes private reporting through
GitHub Security Advisories.

## Maintenance expectations

This project is maintained on a best-effort basis. Issues are read and
triaged, but there is no guaranteed response time — the 7-day first-response
commitment in [SECURITY.md](SECURITY.md) applies to security reports only.
