---
name: running-dbt-commands
description: Run the right dbt Core command with the right selector and flags — dbt build/run/test/seed/snapshot/compile/parse/docs/source freshness/run-operation/retry/clean/deps/debug/ls/show, node selection syntax (graph operators, tag:, source:, config:, state:, result:, test_type:, exposure:, package:), YAML selectors, threading, target selection, vars, full-refresh, defer, and safe execution practice. Use when deciding which dbt command to run, when a selector isn't matching what you expect, before running anything against production, or when asked "how do I run just X" or "what does this flag do".
---

# Running dbt Commands

Getting the command and selector right is the difference between a two-minute build and a
forty-minute one — and between rebuilding one model and rebuilding production.

## Safety first

Before running anything that writes:

1. **Check the target.** `dbt debug` prints it. `--target prod` is one keystroke from
   `--target dev`, and the shell will not warn you.
2. **Dry-run the selector.** `dbt ls --select <selector>` lists exactly what would run,
   costs nothing, and catches the selector that matched 300 models instead of 3.
3. **Know the cost of `--full-refresh`** on a large incremental model before typing it.
4. **Never run `dbt run-operation` with a destructive macro against prod** without reading
   the compiled SQL first.

`dbt ls --select <selector>` before `dbt build --select <selector>` is a habit worth having
permanently.

## The commands

| Command | Does | Notes |
|---|---|---|
| `dbt build` | models + tests + seeds + snapshots, **in DAG order, tests interleaved** | **The default.** Stops dependents when a test fails |
| `dbt run` | models only | Use only when you deliberately want no tests |
| `dbt test` | tests only | For re-running tests without rebuilding |
| `dbt seed` | loads CSVs from `seeds/` | `--full-refresh` to recreate with new types |
| `dbt snapshot` | runs snapshots | Often on a tighter schedule than marts |
| `dbt compile` | renders Jinja → SQL in `target/compiled/` | The debugging workhorse |
| `dbt parse` | parses the project, writes `manifest.json` | Fast, no warehouse. Enough for every script here |
| `dbt docs generate` | builds `catalog.json` + the docs site | Queries information_schema; needs a connection |
| `dbt docs serve` | serves the site locally | |
| `dbt source freshness` | checks source SLAs, writes `sources.json` | Run before the build; a stale source makes the build pointless |
| `dbt run-operation <macro>` | executes a macro | `--args '{"key": "value"}'` |
| `dbt retry` | re-runs only what failed in the last invocation | Reads `run_results.json`. Saves a lot of time |
| `dbt clean` | deletes `target/` and `dbt_packages/` | |
| `dbt deps` | installs packages | First thing in CI, always |
| `dbt debug` | tests the connection and config | Run it before believing any other error |
| `dbt ls` / `dbt list` | lists nodes matching a selector | Free. Use constantly |
| `dbt show --select <model>` | previews a model's output | `--limit 10`. Does not materialize |

### Why `build` and not `run` then `test`

`dbt run` then `dbt test` builds **every** model — propagating bad data through the whole
DAG — and only then discovers the failure. `dbt build` runs each model, immediately runs
its tests, and skips that model's dependents if a test fails. The bad data stops at the
first model instead of reaching the dashboard.

There is no situation where run-then-test is better. Use `build`.

## Node selection

### Graph operators

```bash
dbt build --select fct_orders          # just this model
dbt build --select fct_orders+         # it and everything downstream
dbt build --select +fct_orders         # it and everything upstream
dbt build --select +fct_orders+        # the whole vertical slice
dbt build --select 2+fct_orders        # 2 levels upstream only
dbt build --select fct_orders+2        # 2 levels downstream only
dbt build --select @fct_orders         # it, its ancestors, AND all descendants of those
                                       # ancestors — the "rebuild everything that could be
                                       # affected" selector
```

`@` is the one people forget. It is what you want when an upstream change might affect
siblings you did not think about.

### Methods

```bash
dbt build --select path:models/marts/finance      # by directory
dbt build --select tag:daily                       # by tag
dbt build --select source:shopify+                 # everything from one source
dbt build --select config.materialized:incremental
dbt build --select config.tags:pii
dbt build --select package:dbt_utils
dbt build --select exposure:executive_revenue_dashboard
dbt build --select metric:revenue
dbt build --select test_type:unit                  # unit | data | generic | singular
dbt build --select test_name:relationships
dbt build --select group:finance
dbt build --select access:public
dbt build --select version:latest                  # latest | prerelease | old | none
dbt build --select result:error+                   # everything that errored last run, + downstream
dbt build --select result:fail
dbt build --select state:modified+                 # changed since --state, and downstream
dbt build --select state:new
dbt build --select fqn:analytics.marts.finance.fct_orders
dbt build --select file:fct_orders.sql
```

### Combining

```bash
dbt build --select tag:finance tag:daily              # space = UNION (either)
dbt build --select tag:finance,tag:daily              # comma = INTERSECTION (both)
dbt build --select marts.finance+ --exclude tag:slow  # exclude wins over select
dbt build --select "state:modified+,tag:finance"      # modified AND finance
dbt build --select "+fct_orders" --exclude "source:*" # everything upstream except sources
```

Space is OR, comma is AND. Getting these backwards is the most common selector mistake and
produces a silently wrong build scope — which is why `dbt ls` first matters.

### YAML selectors

Long selectors belong in `selectors.yml`, not in a runbook:

```yaml
# selectors.yml
selectors:
  - name: nightly_finance
    description: Finance marts and everything they need, excluding slow reconciliation tests.
    default: false
    definition:
      union:
        - method: tag
          value: finance
        - method: path
          value: models/marts/finance
      exclude:
        - method: tag
          value: slow

  - name: ci_changed
    description: Slim CI — what changed and its children.
    definition:
      method: state
      value: modified
      children: true
```

```bash
dbt build --selector nightly_finance
```

Named, reviewable, and diffable. Any selector used in production should live here.

## Flags that matter

| Flag | Effect |
|---|---|
| `--target prod` | picks the output from `profiles.yml`. **Check it before every write** |
| `--threads 8` | overrides the profile's thread count |
| `--full-refresh` | rebuilds incremental models from scratch |
| `--vars '{"key": "value"}'` | passes vars; JSON on one line |
| `--defer --state prod/` | unselected `ref`s resolve to prod — the core of slim CI |
| `--favor-state` | with defer, prefer the state manifest even when a local relation exists |
| `--empty` | builds with `limit 0` — validates SQL and schema with no data cost |
| `--fail-fast` / `-x` | stop on the first failure |
| `--warn-error` | treat warnings as errors. Use in CI |
| `--warn-error-options '{"error": ["NoNodesForSelectionCriteria"]}'` | selective escalation |
| `--store-failures` | write failing test rows to a table |
| `--exclude-resource-type test` | build models without tests (rare; be deliberate) |
| `--no-partial-parse` | force a full reparse when the parse cache is suspect |
| `--profiles-dir` / `--project-dir` | non-default locations |
| `--log-format json` | structured logs for an orchestrator |
| `-q` / `--quiet` | suppress everything but errors and `dbt show` output |
| `--debug` | full stack traces and every SQL statement |

`--empty` deserves attention: `dbt build --select state:modified+ --empty` validates that
every changed model compiles and produces the right schema, with zero data scanned. It is
the cheapest possible CI check and catches most breakages.

## Recipes

```bash
# Daily production build
dbt deps && dbt source freshness && dbt build --target prod --threads 12

# Slim CI
dbt deps
dbt build --select state:modified+ --defer --state prod/ --target ci --warn-error

# Cheapest possible CI validation (no data scanned)
dbt build --select state:modified+ --defer --state prod/ --empty

# Iterate on one model
dbt build --select fct_orders
dbt show --select fct_orders --limit 20

# I changed a staging model — what needs rebuilding?
dbt ls --select stg_shopify__orders+
dbt build --select stg_shopify__orders+

# Something failed; re-run only the failures
dbt retry
dbt build --select result:error+

# Rebuild everything an upstream change could have touched
dbt build --select @stg_shopify__orders

# Unit tests only, fast
dbt test --select test_type:unit

# Backfill one incremental model
dbt build --select fct_orders --full-refresh --target prod

# Microbatch backfill window (2.0)
dbt run --select fct_orders --event-time-start 2024-01-01 --event-time-end 2024-02-01

# Read the generated SQL
dbt compile --select fct_orders && cat target/compiled/analytics/models/marts/fct_orders.sql

# Refresh artifacts for the scripts in this repo (no warehouse needed)
dbt parse
```

## Artifacts

Everything the scripts in this repo read comes from `target/`:

| File | Written by | Contains |
|---|---|---|
| `manifest.json` | any command | every node, its config, refs, columns, tests, description — the project's full graph |
| `run_results.json` | `run`/`build`/`test`/`seed`/`snapshot` | per-node status, timing, error text, adapter response |
| `sources.json` | `source freshness` | per-source freshness status and max loaded-at |
| `catalog.json` | `docs generate` | actual warehouse column names, types, and stats |
| `semantic_manifest.json` | any command (with MetricFlow) | semantic models and metrics |

`dbt parse` writes `manifest.json` without touching the warehouse — that is all most of
these scripts need.

**Store production artifacts.** Slim CI, freshness monitoring, and breaking-change detection
all read the last production `manifest.json`. Upload `target/*.json` from every production
run to S3/GCS, and download them in CI.

## Troubleshooting selectors

| Symptom | Cause |
|---|---|
| Nothing matched | Typo, or the node is disabled. `dbt ls --select <sel>` shows empty; check `dbt ls` unfiltered |
| Too much matched | Space where you meant comma — space is OR |
| `state:modified` matches everything | The `--state` manifest is from a different dbt version, a different project, or is stale |
| `state:modified` matches nothing after a real change | `--state` points at the current `target/` — it must point at the *previous* manifest |
| Selector works locally, not in CI | `dbt deps` did not run, so package nodes are missing from the graph |
| `--defer` still rebuilds upstream | The upstream model is *selected*; defer only applies to nodes not in the selection |
| Tag selector misses a model | Tags set in `dbt_project.yml` are additive with in-file ones; check the resolved config with `dbt ls --select <model> --output json` |

## Anti-patterns

- `dbt run` then `dbt test` in production. Propagates bad data through the DAG before
  anything fails.
- `dbt build` with no selector in CI. It rebuilds the whole project on every PR and the team
  disables the check within a month.
- `--full-refresh` reflexively on failure. It masks incremental logic bugs and costs money.
- Running against `--target prod` from a laptop. Production runs come from the orchestrator,
  with artifacts stored.
- A twelve-clause selector pasted into a cron job instead of a named entry in `selectors.yml`.
- `--exclude` used to work around a broken test instead of fixing or scoping the test.
- Ignoring `dbt ls` and discovering the scope from the build log.

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| `/dbt-build` | The selector, the acceptance bar, and the cost — agreed before anything runs |
| "rebuild what my change affects" | `dbt ls` first to show the scope, then `dbt build --select <model>+` |
| "my selector matched nothing" | The resolved config via `dbt ls --output json`, and the flag that makes it fail loudly |
| "re-run just the failures" | `dbt retry`, or `--select result:error+` against the last `run_results.json` |

**Worked example**

> "I changed stg_shopify__orders — what do I need to rebuild?"

```bash
# 1. See the scope before spending warehouse time on it
dbt ls --select stg_shopify__orders+ --output name
#   stg_shopify__orders
#   int_orders_categorized
#   fct_orders
#   dim_customer_orders            ← the one people forget is downstream

# 2. Cheapest validation first — no data scanned
dbt compile --select stg_shopify__orders+

# 3. Build the path, with tests interleaved
dbt build --select stg_shopify__orders+

# 4. Something failed — re-run only the failures, not the DAG
dbt retry
#   or, explicitly, from the stored artifacts:
dbt build --select result:error+ --state target/
```

For CI, the selector is `state:modified+` against a deferred production manifest, with
missing-node detection turned into an error:

```bash
dbt build --select state:modified+ --defer --state prod/ \
    --warn-error-options '{"error":["NoNodesForSelectionCriteria"]}'
```

Without that flag a typo in the selector exits 0 having built nothing, which reads as a
green CI run.

Next: [ops-and-deployment](../ops-and-deployment/SKILL.md).
Reference: [references/dbt_core_cli.md](../../../references/dbt_core_cli.md).
