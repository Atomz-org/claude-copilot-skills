---
description: Sync project memory and graph context after dbt or repo automation changes
argument-hint: [summary of the work performed]
---

Synchronize context for: **$ARGUMENTS**

```bash
./scripts/sync_context.sh "$ARGUMENTS"
```

Use this after `dbt build`, `dbt test`, or analyzer runs so the repository keeps:

- markdown and JSON memory state,
- a current graph snapshot,
- an artifact checkpoint for traceability.
