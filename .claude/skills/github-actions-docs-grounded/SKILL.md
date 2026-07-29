---
name: github-actions-docs-grounded
description: Answer GitHub Actions questions with official docs-first guidance and explicit links, avoiding stale memory.
---

# GitHub Actions Docs Grounded

Use this skill when the request is about GitHub Actions concepts, workflow syntax,
runners, security patterns, reusable workflows, environments, or migration to Actions.

## Workflow

1. Classify the question:
   - syntax/events/contexts,
   - runners/execution,
   - security/tokens/OIDC,
   - deploy/environments,
   - migration.
2. Prefer official docs on `docs.github.com`.
3. Provide a direct answer first, then links to exact pages.
4. Mark any inference explicitly.

## Output shape

1. Direct answer.
2. Relevant official docs links.
3. YAML example only if needed.
4. Inference note if multiple docs were combined.

## Guardrails

- Do not answer from memory alone when details can drift.
- Do not link only to the docs homepage when a specific page exists.
- Route repo-specific failing CI debugging to local troubleshooting commands.
