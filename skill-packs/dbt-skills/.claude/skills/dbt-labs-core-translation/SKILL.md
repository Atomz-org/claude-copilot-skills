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

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| "the dbt docs say to use the Discovery API" | The Core equivalent — the same answer from `manifest.json`, run locally |
| "set up a Cloud job for this" | The orchestration translated to cron / Airflow / GitHub Actions calling the CLI |
| "check lineage in the UI" | `model_dependency_analyzer.py`, optionally `--mermaid` for a diagram |

**Worked example — a Cloud-shaped instruction, translated**

> "use the Discovery API to find models with no tests"

| Cloud-only guidance | dbt Core equivalent here |
|---|---|
| Discovery API — model metadata | `target/manifest.json` after `dbt parse` |
| Discovery API — test coverage | `python scripts/test_coverage_reporter.py --manifest target/manifest.json --layer marts --min-coverage 0.9` |
| Cloud lineage view | `python scripts/model_dependency_analyzer.py --manifest target/manifest.json --model <model> --direction down --mermaid` |
| Cloud job scheduler | cron / Airflow / GitHub Actions running `dbt build --select <selector>` |
| Cloud Semantic Layer API | `mf validate-configs` and `mf query` against the local project |
| Cloud CI "defer to production" | `--defer --state prod/` with stored production artifacts |

```bash
dbt deps && dbt parse
python scripts/test_coverage_reporter.py \
    --manifest target/manifest.json --layer marts --min-coverage 0.9
```

Every translated answer stays reproducible on a machine you control. Where no Core
equivalent exists, say that plainly rather than substituting something that only looks
similar.
