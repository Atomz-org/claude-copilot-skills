---
name: troubleshooting-dbt-job-errors-core
description: Diagnose dbt Core failures and regressions using run artifacts and targeted rebuilds.
---

# Troubleshooting dbt Job Errors (Core)

## Triage loop

1. Read `target/run_results.json` and identify failing node(s).
2. Re-run only affected selector path.
3. Compare against prior artifacts if available.

## Commands

```bash
python scripts/run_results_analyzer.py --run-results target/run_results.json --manifest target/manifest.json --top 20
python scripts/source_freshness_monitor.py --sources target/sources.json --manifest target/manifest.json
python scripts/model_dependency_analyzer.py --manifest target/manifest.json --model <node> --direction down
```

## Root-cause categories

- Parse/compile errors.
- Warehouse/runtime SQL errors.
- Data quality test failures.
- Performance regressions and critical path shifts.

## dbt Core translation notes

- Use artifact-first triage rather than rerunning full DAGs.
- Keep fixes scoped and verify with `dbt build --select <node>+`.
