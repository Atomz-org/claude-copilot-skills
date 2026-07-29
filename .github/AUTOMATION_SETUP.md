# Automation Setup

This repository includes Claude- and Copilot-friendly automation scaffolding for local validation, Git workflow enforcement, and repository hygiene.

## What is included
- Python-based tests under tests/
- Shell-based command helpers under .claude/commands/ for branch, commit, review, ship, and submodule workflows
- GitHub workflow definitions under .github/workflows/ for Claude review, CI quality gates, PR-to-issue automation, and smart sync
- Contributor guidance in docs/ and .github/

## Git workflow expectations
- Protect the main branch from direct commits.
- Enforce branch naming in the form <type>/<ticket>-<description>.
- Enforce Conventional Commit messages such as feat:, fix:, chore:, and docs:.
- Use the shared git-standard helper before committing or opening a PR.
- Standardize issue and PR labels with project-board-style status values: `status: triage`, `status: backlog`, `status: ready`, `status: in-review`, and `status: done`.
- Use priority markers such as `P0`, `P1`, `P2`, and `P3`, plus type labels like `type: bug` and `type: enhancement`.

## Local validation
Run the following from the repository root:

```bash
source .venv/bin/activate
pytest -q
```
