# dbt Core CLI Reference

Every command, selector, and flag, plus the artifacts they produce. Version notes are marked
where behavior differs; check `dbt --version` before relying on a version-gated feature.

## Commands

| Command | Writes | Needs warehouse |
|---|---|---|
| `dbt build` | `manifest.json`, `run_results.json` | yes |
| `dbt run` | same | yes |
| `dbt test` | same | yes |
| `dbt seed` | same | yes |
| `dbt snapshot` | same | yes |
| `dbt compile` | `manifest.json`, `target/compiled/` | yes (for introspective macros) |
| `dbt parse` | `manifest.json` | **no** |
| `dbt docs generate` | `catalog.json`, `index.html` | yes |
| `dbt docs serve` | — | no |
| `dbt source freshness` | `sources.json` | yes |
| `dbt run-operation <macro>` | — | yes |
| `dbt retry` | `run_results.json` | yes |
| `dbt clean` | deletes `target/`, `dbt_packages/` | no |
| `dbt deps` | `dbt_packages/`, `package-lock.yml` | no |
| `dbt debug` | — | yes |
| `dbt ls` / `dbt list` | — | no |
| `dbt show --select <m>` | — | yes |
| `dbt init <name>` | a new project | no |
| `dbt sl query` / `dbt sl export` | — | yes (1.10+, MetricFlow) |

### `dbt build` — the default

Runs models, tests, seeds, and snapshots in DAG order with **tests interleaved**: each
model's tests run immediately after the model, and a failure skips that model's dependents.

`dbt run` followed by `dbt test` builds the entire DAG on bad data before anything fails.
There is no case where that is preferable.

### `dbt retry`

Re-runs only the nodes that failed or were skipped in the last invocation, reading
`run_results.json`. Turns a partial production failure into a two-minute recovery. Requires
`target/run_results.json` from the failed run to still be present.

### `dbt show`

```bash
dbt show --select fct_orders --limit 20
dbt show --inline "select * from {{ ref('fct_orders') }} where order_id = '123'"
```

Previews output without materializing. `--inline` is the fastest way to poke at a model's
result during development.

### `dbt run-operation`

```bash
dbt run-operation generate_source --args '{"schema_name": "shopify", "database_name": "raw"}'
dbt run-operation grant_select --args '{"role": "REPORTER"}'
```

Executes a macro. `--args` is JSON on one line. Read the compiled SQL before running one
that writes.

## Node selection

### Graph operators

| Syntax | Selects |
|---|---|
| `model_name` | that node |
| `model_name+` | it and all descendants |
| `+model_name` | it and all ancestors |
| `+model_name+` | the full vertical slice |
| `2+model_name` | 2 levels of ancestors |
| `model_name+3` | 3 levels of descendants |
| `@model_name` | it, its ancestors, and **all descendants of those ancestors** |
| `model_a model_b` | union (space = OR) |
| `model_a,model_b` | intersection (comma = AND) |

`@` is the "rebuild everything this change could have affected" selector — it catches
siblings that share an upstream dependency.

Space is OR and comma is AND. Reversing them silently changes the build scope, which is why
`dbt ls --select <sel>` before `dbt build --select <sel>` is worth the two seconds.

### Methods

| Method | Example | Selects |
|---|---|---|
| `path` | `path:models/marts/finance` | by directory |
| `file` | `file:fct_orders.sql` | by filename |
| `fqn` | `fqn:analytics.marts.finance.fct_orders` | by fully-qualified name |
| `tag` | `tag:daily` | by tag |
| `source` | `source:shopify` / `source:shopify.orders` | source nodes |
| `resource_type` | `resource_type:model` | model, test, seed, snapshot, source, exposure, metric, saved_query, unit_test |
| `config` | `config.materialized:incremental` | by resolved config |
| `package` | `package:dbt_utils` | nodes from a package |
| `exposure` | `exposure:exec_dashboard` | an exposure (use `+exposure:x` for its upstream) |
| `metric` | `metric:revenue` | a metric |
| `group` | `group:finance` | by group |
| `access` | `access:public` | by access modifier |
| `version` | `version:latest` \| `prerelease` \| `old` \| `none` | by model version |
| `test_type` | `test_type:unit` \| `data` \| `generic` \| `singular` | by test kind |
| `test_name` | `test_name:relationships` | by generic test name |
| `state` | `state:modified+` | vs a prior manifest |
| `result` | `result:error+` \| `fail` \| `warn` \| `success` \| `skipped` | vs a prior `run_results.json` |
| `saved_query` | `saved_query:weekly_revenue` | a saved query |

### `state:` sub-selectors

Require `--state <dir containing manifest.json>`.

| Selector | Matches |
|---|---|
| `state:new` | absent from the state manifest |
| `state:modified` | any change — body, config, tests, descriptions, macros used |
| `state:modified.body` | SQL body only |
| `state:modified.configs` | config only |
| `state:modified.relation` | database/schema/alias changed |
| `state:modified.persisted_descriptions` | description changed with `persist_docs` on |
| `state:modified.macros` | a macro the node depends on changed |
| `state:modified.contract` | the contract changed — the breaking-change gate |
| `state:old` | in state but not in the current project |

`state:modified` is deliberately broad. `--state` must point at the **previous** (production)
manifest, never the current `target/` — pointed at the current one it matches nothing and CI
validates nothing.

### YAML selectors

```yaml
# selectors.yml
selectors:
  - name: nightly_finance
    description: Finance marts and their upstream, excluding slow reconciliation tests.
    default: false
    definition:
      union:
        - method: tag
          value: finance
        - method: path
          value: models/marts/finance
          parents: true
      exclude:
        - method: tag
          value: slow

  - name: ci_changed
    definition:
      method: state
      value: modified
      children: true
```

```bash
dbt build --selector nightly_finance
```

Definition keys: `method`, `value`, `children`, `parents`, `children_depth`, `parents_depth`,
`childrens_parents` (the `@` operator), `indirect_selection`
(`eager` | `cautious` | `buildable` | `empty`).

`indirect_selection` controls whether a test attached to both a selected and an unselected
model runs. `eager` (default) runs it; `cautious` runs it only if every parent is selected.
Use `cautious` in CI to avoid tests failing on unbuilt models.

Any selector used in production belongs here — named, reviewable, and diffable.

## Flags

### Selection
`--select` / `-s`, `--exclude`, `--selector`, `--resource-type`, `--exclude-resource-type`

### Execution
| Flag | Effect |
|---|---|
| `--target` / `-t` | which output in `profiles.yml`. **Check before every write** |
| `--threads` | override the profile thread count |
| `--full-refresh` | rebuild incremental models from scratch |
| `--vars '{"k":"v"}'` | pass vars; JSON on one line |
| `--defer` + `--state <dir>` | unselected `ref`s resolve to the state manifest's relations |
| `--favor-state` | prefer state relations even when a local one exists |
| `--empty` | build with `limit 0` — validates SQL and schema, scans no data |
| `--fail-fast` / `-x` | stop on the first failure |
| `--store-failures` | write failing test rows to a table |
| `--event-time-start` / `--event-time-end` | microbatch window (2.0) |

### Output and logging
| Flag | Effect |
|---|---|
| `--warn-error` | warnings become errors. Use in CI |
| `--warn-error-options '{"error":["Deprecations"]}'` | selective escalation |
| `--log-format json` | structured logs for an orchestrator |
| `--log-level debug` | |
| `--debug` / `-d` | stack traces and every SQL statement |
| `--quiet` / `-q` | errors and `dbt show` output only |
| `--no-print` | suppress `{{ print() }}` |
| `--output json` | `dbt ls` output as JSON — the resolved config per node |

### Project
`--project-dir`, `--profiles-dir`, `--profile`, `--no-partial-parse`, `--no-version-check`,
`--use-colors` / `--no-use-colors`

Global flags go **before** the subcommand: `dbt --debug run`, not `dbt run --debug`. Some
work in both positions, which makes the failures confusing — put them first.

## Artifacts

All in `target/`.

### `manifest.json`

The complete project graph. Every script in this scaffold reads it.

```
nodes.<unique_id>            models, tests, snapshots, seeds, unit tests
  .resource_type             model | test | snapshot | seed | operation | unit_test
  .name .database .schema .alias .path .original_file_path
  .depends_on.nodes[]        upstream unique_ids
  .depends_on.macros[]
  .config                    materialized, tags, group, access, contract, meta, ...
  .columns.<name>            .description .data_type .meta .tags
  .description
  .tests[] / .test_metadata  for test nodes: .name .kwargs
  .compiled_code .raw_code
  .patch_path                the YAML file that documented it
  .access .group .version .latest_version .deprecation_date
sources.<unique_id>          .freshness .loaded_at_field .source_name .identifier
exposures.<unique_id>        .type .owner .url .depends_on
metrics.<unique_id>
semantic_models.<unique_id>
saved_queries.<unique_id>
parent_map / child_map       adjacency lists — the fastest way to walk the DAG
group_map
metadata                     .dbt_version .project_name .generated_at .adapter_type
```

`parent_map` and `child_map` are pre-computed adjacency lists — use them rather than walking
`depends_on` yourself.

### `run_results.json`

```
results[]
  .unique_id
  .status                    success | error | skipped | fail | warn | pass | runtime error
  .execution_time            seconds
  .message                   the error text
  .failures                  failing row count for tests
  .adapter_response          rows_affected, bytes_processed, query_id (adapter-specific)
  .timing[]                  {name: compile|execute, started_at, completed_at}
elapsed_time                 total wall-clock
args                         the invocation's flags — useful for reproducing
metadata.generated_at .dbt_version .invocation_id
```

### `sources.json`

```
results[]
  .unique_id
  .status                    pass | warn | error | runtime error
  .max_loaded_at
  .snapshotted_at
  .max_loaded_at_time_ago_in_s
  .criteria.warn_after / .error_after
```

### `catalog.json`

Real warehouse metadata from `dbt docs generate`: actual column names, types, ordinal
positions, and table stats. The authoritative source for `data_type` when writing a contract.

### `semantic_manifest.json`

Semantic models, metrics, and saved queries, as MetricFlow resolved them.

### Storing artifacts

Upload `target/*.json` from every production run — including failed ones — to object storage.
`state:modified`, `--defer`, freshness monitoring, performance comparison, and every script
in this scaffold depend on having the previous production artifacts available.

## Environment variables

| Variable | Effect |
|---|---|
| `DBT_PROFILES_DIR` | where `profiles.yml` lives |
| `DBT_PROJECT_DIR` | project root |
| `DBT_TARGET` | default target |
| `DBT_THREADS` | default thread count |
| `DBT_STATE` | default `--state` directory |
| `DBT_DEFER` | enable defer by default |
| `DBT_LOG_PATH` / `DBT_TARGET_PATH` | relocate `logs/` and `target/` |
| `DBT_PARTIAL_PARSE` | `false` disables the parse cache |
| `DBT_SEND_ANONYMOUS_USAGE_STATS` | `false` opts out |
| `DBT_ENV_SECRET_<NAME>` | scrubbed from logs — use for anything sensitive |

In the project, `{{ env_var('X') }}` fails the run when unset (correct for a secret);
`{{ env_var('X', 'default') }}` supplies a fallback.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | a node failed, or a test failed at `error` severity |
| 2 | dbt itself errored — bad config, connection failure, parse error |

An orchestrator should treat 1 and 2 differently: 1 is a data problem for the model owner, 2
is a platform problem.

## Common invocations

```bash
# Production
dbt deps && dbt source freshness && dbt build --target prod --threads 12

# Slim CI
dbt deps && dbt build --select state:modified+ --defer --state prod/ --target ci --warn-error

# Zero-cost CI validation
dbt build --select state:modified+ --defer --state prod/ --empty

# Refresh artifacts for the scripts here — no warehouse needed
dbt parse

# What would this selector actually do?
dbt ls --select "state:modified+,tag:finance" --output json

# Re-run only failures
dbt retry

# Read what actually ran
dbt compile --select fct_orders && cat target/compiled/analytics/models/marts/fct_orders.sql
```
