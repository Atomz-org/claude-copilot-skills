---
name: pr-reviewability-prep
description: Prepare a branch or PR for fast reviewer comprehension without changing intended behavior.
---

# PR Reviewability Prep

Use this skill when the code works but the PR is hard to review.

## Workflow

1. Inspect commit list, changed files, and diff size.
2. Detect reviewability problems:
   - mixed mechanical and behavior changes,
   - stale PR description,
   - unclear reviewer entry points,
   - missing test evidence.
3. Propose a plan before any history rewrite.
4. If rewriting is approved, preserve behavior intent and verify resulting diff/tree.
5. Produce reviewer guidance:
   - TL;DR,
   - high-risk files,
   - test evidence,
   - rollout/rollback notes.

## Guardrails

- Do not hide behavior changes in cleanup commits.
- If diff remains too large, recommend splitting the PR.
