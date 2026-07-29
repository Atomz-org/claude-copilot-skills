---
name: pr-review-terse-comments
description: Produce concise, actionable review comments with location, impact, and fix.
---

# PR Review Terse Comments

## Format

- Single-file: `L<line>: <severity> <problem>. <fix>.`
- Multi-file: `<file>:L<line>: <severity> <problem>. <fix>.`

Where severity is one of:

- `bug`
- `risk`
- `nit`
- `q`

## Rules

- No throat-clearing phrases.
- No restating obvious code behavior.
- Mention exact symbol names when possible.
- Include why when the fix is not obvious.

## Auto-clarity exception

Use fuller explanation for security, major architecture tradeoffs, or onboarding-critical issues.
