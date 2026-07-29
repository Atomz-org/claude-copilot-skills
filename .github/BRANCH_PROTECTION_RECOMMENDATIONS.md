# Branch Protection Recommendations

This repository is ready for strict protection on the default branch.

## Recommended protected branches

- `main`: strict protection
- `develop` (if used): medium protection

## Recommended rules for main

1. Require a pull request before merging.
2. Require at least 1 approving review.
3. Dismiss stale approvals when new commits are pushed.
4. Require review from code owners (optional, if CODEOWNERS is maintained).
5. Require all conversations to be resolved before merge.
6. Require status checks to pass before merging.
7. Require branches to be up to date before merging.
8. Require linear history.
9. Block force pushes.
10. Block branch deletion.
11. Apply rules to administrators.

## Required status checks

Use these exact job checks:

- `CI Lite / test-and-sync`
- `Repository Baseline / baseline`
- `CI Quality Gate / quality-gate`

Recommended optional check:

- `Claude Code Review / review` (labeling and context only, not a hard quality gate)

## Suggested merge strategy

- Allow squash merge.
- Disable merge commit if you want linear history clarity.
- Optional: keep rebase merge enabled for teams that prefer it.

## Suggested release safety

- Restrict direct pushes to `main`.
- Require release tags to be created only through workflow dispatch.
- Protect tag pattern `v*` in repository settings (if your plan supports tag protection).

## GitHub UI setup checklist

1. Open repository Settings.
2. Go to Branches.
3. Add branch protection rule for `main`.
4. Enable the rules above.
5. Add required status checks listed in this document.

## GitHub CLI quick verification

Use this after setup to inspect current protection state:

```bash
gh api repos/:owner/:repo/branches/main/protection
```

Replace `:owner/:repo` with your repository path.
