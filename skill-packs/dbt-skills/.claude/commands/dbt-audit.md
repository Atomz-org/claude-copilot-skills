---
description: Run the dbt project health sweep and return a ranked, actionable list
argument-hint: "[path or layer, defaults to the whole project]"
---

Audit the project: **$ARGUMENTS**

---

## 1. Refresh the manifest

```bash
dbt deps && dbt parse
```

`dbt parse` writes `manifest.json` without touching the warehouse — that is all these
tools need. If a check reports everything as undocumented, the manifest is stale.

## 2. Run the sweep

```bash
python scripts/dbt_project_auditor.py --manifest target/manifest.json
python scripts/test_coverage_reporter.py --manifest target/manifest.json --top 20
python scripts/model_dependency_analyzer.py --manifest target/manifest.json
python scripts/model_dependency_analyzer.py --manifest target/manifest.json --check-layers
python scripts/semantic_layer_validator.py --path models/
```

With production artifacts available, add:

```bash
python scripts/run_results_analyzer.py --run-results prod/run_results.json \
    --manifest target/manifest.json --top 20
python scripts/source_freshness_monitor.py --sources prod/sources.json \
    --manifest target/manifest.json
python scripts/contract_breaking_change_detector.py \
    --base prod/manifest.json --head target/manifest.json
```

## 3. Rank by consequence, not by count

The tools already sort by downstream blast radius. Preserve that ordering in your report,
and group findings into three buckets:

| Bucket | Contents |
|---|---|
| **Fix now** | untested models feeding exposures, hardcoded refs, sources with no freshness, incremental models with no `unique_key`, contract violations, DAG cycles |
| **Fix this quarter** | undocumented models with real downstream reach, missing unit tests on logic-heavy models, layer violations, `on_schema_change: ignore` |
| **Delete instead of fixing** | orphan marts with no consumer, models nobody queries |

That third bucket is usually the highest-value one. A mart with no downstream model and no
exposure costs build time, test time, and review time on **every single run** — deleting it
is a bigger win than testing it.

## 4. Report each finding usefully

For each: **what it is, what would break in production, and the fix.** A finding you cannot
state a failure mode for is a preference — label it as one or drop it.

Do not produce a flat list of 200 items. Nobody acts on that. Produce:

- the 5–10 things that would actually cause an incident, with names;
- the pattern behind them (e.g. "no source has a freshness block" is one finding, not
  fourteen);
- a concrete first PR that fixes the top cluster.

## 5. Complementary tooling worth mentioning

`dbt_project_evaluator` (dbt Labs' own package) runs best-practice checks **in** the
warehouse against a built manifest. It overlaps with `dbt_project_auditor.py` and adds
checks this scaffold does not have. The script here runs offline in CI from `manifest.json`
alone; the package runs deeper. Recommend both if the project has neither.

## 6. Wire the gates into CI

Once the top findings are fixed, keep them fixed:

```bash
python scripts/dbt_project_auditor.py --manifest target/manifest.json --strict
python scripts/test_coverage_reporter.py --manifest target/manifest.json \
    --layer marts --min-coverage 0.9 --strict
python scripts/contract_breaking_change_detector.py \
    --base prod/manifest.json --head target/manifest.json --strict
```

All three exit 1 on failure and run in seconds with no warehouse connection. An audit that
does not become a gate is an audit you repeat in six months.

---

## Output

1. **Verdict** — is this project healthy, and what is the single biggest risk?
2. **Fix now** — named findings, each with its failure mode and fix.
3. **Fix this quarter** — grouped by pattern, not enumerated.
4. **Delete** — models with no consumer, with the build time they cost.
5. **The first PR** — a concrete, scoped change that fixes the top cluster.
6. **CI gates** to add so it does not regress.

Say plainly when a project is in good shape. An audit that manufactures findings to look
thorough trains people to ignore the next one.
