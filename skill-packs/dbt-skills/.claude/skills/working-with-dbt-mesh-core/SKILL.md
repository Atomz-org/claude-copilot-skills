---
name: working-with-dbt-mesh-core
description: Manage model contracts, versions, groups, and access in dbt Core multi-team or multi-project workflows.
---

# Working with dbt Mesh (Core)

## Core practices

- Use contracts on shared models.
- Use model versions for breaking changes.
- Use groups and access controls for ownership boundaries.

## Breaking-change workflow

1. Identify downstream consumers.
2. Add a new model version instead of in-place destructive edits.
3. Keep previous version during migration window.
4. Add contract check in CI.

## Commands

```bash
python scripts/model_dependency_analyzer.py --manifest target/manifest.json --model <model> --direction down
python scripts/contract_breaking_change_detector.py --base prod/manifest.json --head target/manifest.json --strict
```

## dbt Core translation notes

- Replace platform governance dashboards with manifest-driven checks and repository CI gates.
