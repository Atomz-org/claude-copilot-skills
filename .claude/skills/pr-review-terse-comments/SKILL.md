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

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| "give me review comments I can paste into the PR" | One line per finding, in the format above — nothing else |
| `/review` then "turn those into comments" | The orchestrator's findings compressed to pasteable lines |
| "review this file" | Single-file form, `L<line>:` with no path prefix |

**Worked example**

> "review comments for the checkout diff"

```
src/checkout/tax.ts:L88: bug applyRounding runs per line and again on the total, so 4+ line orders drift 2c. Round once at the total.
src/checkout/tax.ts:L12: risk VAT_RATE is a module constant but the rate is per-region. Pass it in.
src/checkout/tax.ts:L51: q calculateNet returns null on an empty cart — is that reachable from the API?
tests/tax.test.ts:L44: nit test named "negative amount" asserts on zero.
```

Compare with what this skill rejects — same finding, no location, no fix, and a sentence
of throat-clearing before the point:

```
I noticed that there might be an issue with how rounding is being handled here.
It could potentially cause some inconsistencies. You may want to take a look.
```
