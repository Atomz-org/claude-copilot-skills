---
name: documentation-writer-diataxis
description: Create focused technical documentation using Diataxis document types and an outline-first workflow.
---

# Documentation Writer (Diataxis)

Use this skill for clear technical docs.

## Diataxis modes

- Tutorial: learn by doing.
- How-to: solve a specific task.
- Reference: precise technical facts.
- Explanation: conceptual understanding.

## Workflow

1. Clarify audience, goal, document type, and scope.
2. Propose outline and get approval.
3. Write full markdown content with consistent terminology.
4. Validate links, commands, and examples for accuracy.

## Guardrails

- Do not mix document types without stating intent.
- Keep examples runnable and scoped.
- Match repository voice and conventions.

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| `/write-docs onboarding a new connector` | The Diataxis type named and justified, then an outline for approval before any prose |
| "document this module" | A question back: who reads it and to do what — the answer picks the type |
| "our README explains and instructs at once" | A split proposal: how-to stays, the conceptual half moves to an explanation page |

**Worked example**

> `/write-docs how to add a connector`

```
Audience : analytics engineer, already has the dbt project running
Goal     : get one new source system into an existing use-case
Type     : How-to — a specific task with a known end state, not a learning path
Out of scope: why the layering exists (that is an Explanation page)

Outline — approve before I write
  1. Before you start (project runs, raw tables landed, use-case slug known)
  2. Settle the four inputs
  3. Scaffold with the dry run
  4. Fill in sources and staging
  5. Verify: dbt build --select <selector>
  6. Troubleshooting: three failures people actually hit
```

Prose is written after the outline is approved, and every command in it is checked against
the repository rather than recalled.
