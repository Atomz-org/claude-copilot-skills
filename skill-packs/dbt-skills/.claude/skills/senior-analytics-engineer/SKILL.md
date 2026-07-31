---
name: senior-analytics-engineer
description: Compatibility alias for dbt-skill. Use dbt-skill as the canonical entrypoint.
---

# senior-analytics-engineer (Alias)

This compatibility skill exists to prevent missing-skill resolution errors.

Canonical skill entrypoint:

- [dbt-skill](../dbt-skill/SKILL.md)

All new updates should target `dbt-skill`.

## Examples

| Ask Claude | What happens |
|---|---|
| "use the senior-analytics-engineer skill" | Resolves here, then routes to `dbt-skill` — the routing and rules live there |
| A parent repository pinned to the old name | Keeps working; nothing breaks on the rename |
| "add guidance for X to senior-analytics-engineer" | Edit `dbt-skill` instead. This file stays a pointer |

**Worked example**

> "load senior-analytics-engineer and design a churn mart"

```
Alias resolved → dbt-skill
dbt-skill routes → analytics-request-framing (no model before a use-case spec)
Deliverable → skill-packs/dbt-skills/use-cases/<slug>/use-case-spec.md
```

The alias adds no behavior of its own. If the answer differs depending on which name was
used, that is a defect.
