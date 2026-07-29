---
name: using-dbt-for-analytics-engineering-core
description: Build and modify dbt models using dbt Core best practices, source contracts, tests, and artifact-driven validation.
---

# Using dbt for Analytics Engineering (Core)

## Workflow

1. Frame request and define grain.
2. Validate source assumptions from existing docs and artifacts.
3. Design or extend models using `ref()` and `source()` only.
4. Run `dbt build --select <model>+`.
5. Add tests and documentation before merge.

## Must-do checks

- No hardcoded table names.
- Primary keys must have `unique` and `not_null` tests.
- Logic-heavy models must include unit tests.
- Breaking changes must include contracts/versioning updates.

## Helpful scripts

```bash
python scripts/dbt_project_auditor.py --manifest target/manifest.json
python scripts/model_dependency_analyzer.py --manifest target/manifest.json --model <model> --direction down --mermaid
python scripts/contract_breaking_change_detector.py --base prod/manifest.json --head target/manifest.json --strict
```

## dbt Core translation notes

- Replace hosted lineage/exposure checks with local manifest analysis and dependency scripts.
- Treat artifact validation as required for every merge decision.
