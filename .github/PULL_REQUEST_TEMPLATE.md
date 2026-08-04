## Pick a template

## When to use full vs minimal

- Use a full template when the PR is part of a multi-layer stack, has cross-team impact, changes contracts or generated artifacts, or needs explicit dependency and merge-order context.
- Use a minimal template for small 1-2 day changes with a single concern, low risk, and straightforward validation.
- If unsure, start with full and trim only if reviewers do not need the extra context.

Use one of the stacked PR templates in `.github/PULL_REQUEST_TEMPLATE/`:

- `platform-stack-full.md`
- `client-stack-full.md`
- `platform-stack-minimal.md`
- `client-stack-minimal.md`

If your PR is not stacked, you can still use a minimal template and leave stack-specific fields as `none`.

## Quick fallback (if you do not switch templates)

### Summary
- What changed and why?

### Stack
- Stack name:
- Layer (x of n):
- Depends on:
- Blocks:
- Merge order:

### Validation
- [ ] Relevant checks or tests were run
- [ ] Generated artifacts were regenerated when applicable
- [ ] Documentation was updated if needed

### Risk
- Risk level:
- Rollback plan:
