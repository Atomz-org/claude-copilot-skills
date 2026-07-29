---
name: running-dbt-commands-core
description: Run dbt Core commands safely with selectors, strict no-node checks, and artifact-aware validation.
---

# Running dbt Commands (Core)

## Rules

- Prefer `dbt build` over run-then-test for development and CI.
- Always use `--select`.
- Add `--warn-error-options '{"error":["NoNodesForSelectionCriteria"]}'` in CI-safe flows.

## Standard patterns

```bash
dbt ls --select "<selector>"
dbt build --select "<selector>" --warn-error-options '{"error":["NoNodesForSelectionCriteria"]}'
dbt test --select "<selector>"
dbt show --select "<model>" --limit 20
```

## Artifact checks

After command runs, inspect artifacts:

```bash
python scripts/run_results_analyzer.py --run-results target/run_results.json --manifest target/manifest.json
python scripts/test_coverage_reporter.py --manifest target/manifest.json --layer marts --min-coverage 0.9
```

## dbt Core translation notes

- If upstream guidance suggests Cloud/Fusion APIs, translate to local Core command + artifact review.
- Use `--state` and `--defer` only when production artifacts are available locally.
