---
description: Make current branch easier to review without changing behavior intent.
---

Prepare current branch for review.

1. Inspect scope:
   - `git status --short`
   - `git log --oneline --decorate -n 15`
   - `git diff --stat`
2. Identify reviewability issues:
   - mixed concerns,
   - noisy generated/mechanical changes mixed with logic,
   - missing reviewer guidance.
3. Propose cleanup plan before rewriting history.
4. If approved, perform minimal safe reorganization.
5. Verify behavior intent preserved by comparing diff/tree and rerunning tests.
6. Output PR notes with:
   - TL;DR,
   - key files to review first,
   - risk and verification evidence.
