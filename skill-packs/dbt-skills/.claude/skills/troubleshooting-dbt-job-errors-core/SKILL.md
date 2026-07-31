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

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| "the nightly job failed" | `run_results.json` read first — the failing node, its error, and its timing |
| `/dbt-debug` | The same triage, plus the blast radius of the node that broke |
| "just re-run it" | A pushback: re-running blind costs a full build and discards the evidence |

**Worked example**

> "last night's build failed, no idea why"

```bash
python scripts/run_results_analyzer.py \
    --run-results target/run_results.json --manifest target/manifest.json --top 20
```

```
FAIL  test  unique_fct_orders_order_id        0.4s   142 failing rows
SKIP  model dim_customer_orders                      (dependent on failed test)
PASS  model fct_orders                       48.2s   ← ran fine; the data is wrong, not the SQL
```

```bash
# The failing rows were stored — query them instead of guessing
select * from analytics_dbt_test__audit.unique_fct_orders_order_id limit 10;

# Who else is affected before you touch anything
python scripts/model_dependency_analyzer.py \
    --manifest target/manifest.json --model fct_orders --direction down

# Fix, then verify the node and its children only
dbt build --select fct_orders+
```

Category here is a data quality failure, not a SQL error: 142 duplicate `order_id` rows
arrived from a double load upstream. Fixing it in the mart would hide the source defect.
