---
name: dbt-labs-core-translation
description: Translation layer that incorporates dbt-labs/dbt-agent-skills behavior into dbt Core-only workflows used by this repository.
---

# dbt Labs Skills to dbt Core Translation

This repository incorporates dbt Labs skill patterns from dbt-agent-skills and maps them to dbt Core execution.

## Included translated skills

- using-dbt-for-analytics-engineering-core
- running-dbt-commands-core
- building-dbt-semantic-layer-core
- adding-dbt-unit-test-core
- working-with-dbt-mesh-core
- troubleshooting-dbt-job-errors-core

## Translation policy

1. Prefer dbt Core CLI (`dbt`) workflows.
2. Replace platform-only operations with local artifact analysis (`target/manifest.json`, `target/run_results.json`, `target/sources.json`).
3. Keep semantic-layer validation using `mf validate-configs` where available.
4. Keep model-governance guidance (contracts, versions, access), but implement with dbt Core YAML and CI gates.

## Core-first command baseline

```bash
dbt deps
dbt parse
dbt build --select <selector>
dbt test --select <selector>
python scripts/dbt_project_auditor.py --manifest target/manifest.json --strict
```

## Notes

- Upstream source: https://github.com/dbt-labs/dbt-agent-skills
- This translation avoids dbt Cloud-only APIs by default and keeps workflows local and reproducible.
