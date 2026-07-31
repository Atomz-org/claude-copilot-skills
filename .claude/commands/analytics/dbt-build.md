---
description: Decide the dbt build scope and acceptance bar before running anything
argument-hint: <model, selector, or "what changed">
---

Define the build scope for: **$ARGUMENTS**

---

## 1. Confirm the target — before anything else

```bash
dbt debug | grep -i "target\|profile"
```

`--target prod` is one keystroke from `--target dev` and the shell will not warn you.
**Production runs come from the orchestrator, not a laptop.**

## 2. Dry-run the selector

```bash
dbt ls --select "<selector>"
dbt ls --select "<selector>" --output json | python -m json.tool | head -40
```

This costs nothing and catches the selector that matched 300 models instead of 3.
**Space is OR, comma is AND** — reversing them silently changes the scope, which is why
this step is not optional.

Report what would run before running it.

## 3. Pick the right scope

| Situation | Selector |
|---|---|
| Iterating on one model | `<model>` |
| Changed a model, need its dependents | `<model>+` |
| Need upstream built first | `+<model>` |
| Changed something upstream, want everything possibly affected | `@<model>` |
| CI on a PR | `state:modified+ --defer --state prod/` |
| Re-run after a failure | `dbt retry`, or `result:error+` |
| Whole domain | `path:models/marts/finance+` or a named entry in `selectors.yml` |
| Production, excluding expensive tests | `--exclude tag:nightly` |

`@<model>` is the one people forget: it selects the model, its ancestors, **and all
descendants of those ancestors** — the "rebuild everything this change could have affected"
selector.

## 4. Always `build`, never `run` then `test`

```bash
dbt build --select "<selector>"
```

`build` interleaves each model's tests immediately after the model and skips that model's
dependents when a test fails. `dbt run` then `dbt test` builds the **entire** DAG on bad
data and only then discovers the failure. There is no case where run-then-test is better.

## 5. Cheap validation first

```bash
dbt build --select "<selector>" --defer --state prod/ --empty
```

`--empty` builds with `limit 0` — validates that every model compiles, runs, and produces
the right schema, while scanning no data. The cheapest possible check, and it catches most
breakage. Run it before the real build.

## 6. Set the acceptance bar — before running

State what "worked" means, so the result is not judged after the fact:

| Check | Expected |
|---|---|
| Build status | all green |
| Row count vs previous run | within `<x%>` |
| `sum()` of key numeric column | within `<x%>` |
| Max timestamp advanced | yes |
| Build duration | under `<n>` |
| New tests pass | yes |

## 7. If `--full-refresh` is in play

State the cost and duration **before** typing it. On a large incremental model this is real
money and a real window of inconsistency. `--full-refresh` is not a debugging first
response — it masks incremental logic bugs.

## 8. Verify

```bash
python scripts/run_results_analyzer.py --run-results target/run_results.json \
    --manifest target/manifest.json --compare prod/run_results.json --slower-than 1.5
```

Check the acceptance bar from step 6, not just the green build. And open the consumer's
dashboard — green tests with a broken chart happens.

---

## Rules that bind here

[Rules 36–41](../../rules/analytics-engineering-rules.md): `dbt build`, not run-then-test;
CI runs only what changed and its children; production artifacts are stored; every
deployment has a rollback path; failures are diagnosed from artifacts, not by re-running.

## Output

- the exact command, with the target named;
- what `dbt ls` says will run (count and list);
- the acceptance bar;
- the full-refresh cost if applicable;
- the rollback path.
