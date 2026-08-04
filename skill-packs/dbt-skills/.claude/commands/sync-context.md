---
description: Sync project memory and graph context after dbt or repo automation changes
argument-hint: "[summary of the work performed]"
---

Synchronize context for: **$ARGUMENTS**

Run the sync with a decision attached. The summary is what happened; the decision is
why, and only the decision reaches AgentMemory:

```bash
./scripts/sync_context.sh "$ARGUMENTS" \
    --decision "<what was chosen, what was ruled out, and the constraint that forced it>"
```

Write the `--decision` text yourself from the work just completed. Do not restate the
summary — a commit message is already in `git log`, and a second copy in the memory
store only goes stale. Record what a future session could not recover from the
repository:

- a choice between real alternatives, and why the loser lost
  ("merge over delete+insert — the source late-arrives up to 3 days")
- a constraint discovered the hard way
  ("`.venv-dbt` is not pruned by name; graphify only marker-checks `*_env`")
- a correction to something previously believed true

If the work produced no such fact, run without `--decision`. The mirror is skipped and
the checkpoint is still written — that is the correct outcome, not a failure.

Recall is BM25, not embeddings, so phrase the decision with the words a future question
would use. "incremental strategy for fct_orders" is findable; "fixed the thing" is not.

Use this after `dbt build`, `dbt test`, or analyzer runs so the repository keeps:

- markdown and JSON memory state,
- a current graph snapshot,
- an artifact checkpoint for traceability.
