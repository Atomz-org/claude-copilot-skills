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

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| "commit this" | The staged diff read first, then one proposed Conventional Commit message — not a commit already made |
| "split this into commits" | A grouping of the working tree into one logical change per commit, with a message for each |
| "does this need a BREAKING CHANGE footer?" | A verdict from the diff, plus the footer text if the answer is yes |

**Worked example**

> "commit the session timeout fix"

```
$ git diff --cached --stat
 src/auth/session.ts   | 12 +++++-------
 tests/session.test.ts | 24 ++++++++++++++++++++++++

Proposed: fix(auth): expire idle sessions after 30 minutes

Scope   : one logical change — behavior plus its test
Risk    : existing sessions are invalidated on deploy; note it in the PR body
Verify  : ./.claude/commands/git-standard.sh --dry-run "fix(auth): expire idle sessions after 30 minutes"
```

Commit only after the message is confirmed.
