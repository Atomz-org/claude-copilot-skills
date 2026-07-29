---
name: git-commit-quality
description: Produce safe, reviewable Conventional Commits from actual staged diffs with scope and risk awareness.
---

# Git Commit Quality

Use this skill before committing.

## Commit workflow

1. Inspect scope:
   - `git status --porcelain`
   - `git diff --cached --stat`
2. Keep one logical change per commit where possible.
3. Generate message with Conventional Commits:
   - `<type>(optional-scope): <summary>`
4. Keep summary concise and imperative.
5. Include breaking-change marker and footer when applicable.

## Suggested types

- `feat`, `fix`, `docs`, `refactor`, `test`, `ci`, `build`, `chore`, `perf`, `revert`

## Safety protocol

- Never commit secrets.
- Never use force or hard reset in this flow.
- Never skip hooks unless explicitly requested.
- Prefer dry-run validation with `./.claude/commands/git-standard.sh --dry-run "<msg>"`.
