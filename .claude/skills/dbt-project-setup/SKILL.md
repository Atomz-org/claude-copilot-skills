---
name: dbt-project-setup
description: Set up, configure, or repair a dbt Core project — installation and adapters, dbt_project.yml, profiles.yml and targets, environment variables and secrets, packages via packages.yml/dbt deps, directory layout, dbt debug, generating and serving docs, and wiring the dbt MCP server for local dbt Core. Use when there is no project yet, when `dbt debug` or a connection fails, when adding a package or adapter, when configuring dev/prod targets, or when asked "how do I set this up" or "how do I look up dbt docs".
---

# dbt Project Setup

Getting the plumbing right once saves a week of confusing errors later.

## Install

dbt Core is `dbt-core` plus exactly one adapter per warehouse. Always in a virtual
environment — dbt pins its dependencies tightly and will fight your system Python.

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install dbt-core dbt-snowflake      # or dbt-bigquery, dbt-postgres,
                                                  # dbt-databricks, dbt-redshift, dbt-duckdb,
                                                  # dbt-trino, dbt-athena-community
dbt --version                                     # confirms core + adapter versions
```

Pin both in `requirements.txt`, and pin the same versions in CI. A minor-version drift
between a developer's machine and CI produces "works locally" bugs that take hours.

```
dbt-core==1.9.*
dbt-snowflake==1.9.*
dbt-metricflow[snowflake]==0.207.*   # only if using the semantic layer
```

## Initialize

```bash
dbt init analytics          # scaffolds the project and walks through profiles.yml
cd analytics
dbt debug                   # ALWAYS run this before anything else
```

`dbt debug` verifies: the profile is found, credentials work, the connection opens, and the
target schema is reachable. Do not proceed past a failing `dbt debug` — every subsequent
error will be a downstream symptom of it.

## `dbt_project.yml`

```yaml
name: analytics
version: 1.0.0
config-version: 2
profile: analytics                 # must match a key in profiles.yml

model-paths:    [models]
analysis-paths: [analyses]
test-paths:     [tests]
seed-paths:     [seeds]
macro-paths:    [macros]
snapshot-paths: [snapshots]
clean-targets:  [target, dbt_packages]

require-dbt-version: [">=1.8.0", "<2.0.0"]   # fails fast on a version mismatch

vars:
  start_date: '2023-01-01'
  exclude_test_accounts: true

models:
  analytics:
    +persist_docs: {relation: true, columns: true}   # descriptions land in the warehouse
    staging:
      +materialized: view
      +schema: staging
      +tags: [staging]
    intermediate:
      +materialized: ephemeral
      +schema: intermediate
    marts:
      +materialized: table
      +schema: marts
      finance:
        +schema: finance
        +tags: [finance, sensitive]

seeds:
  analytics:
    +schema: seeds
    country_codes:
      +column_types: {country_code: varchar(2)}   # never let dbt infer a seed's types

snapshots:
  analytics:
    +target_schema: snapshots     # snapshots must NOT be environment-suffixed;
                                  # a dev snapshot that diverges is unrecoverable
```

Config precedence, lowest to highest: `dbt_project.yml` → property YAML (`schema.yml`) →
in-file `{{ config() }}`. Set the default in `dbt_project.yml` and override the exceptions.

## `profiles.yml`

Lives at `~/.dbt/profiles.yml` by default, or `--profiles-dir`. **Never commit it with
credentials.** Use `env_var()` for every secret.

```yaml
analytics:
  target: dev                     # the default; override with --target prod
  outputs:
    dev:
      type: snowflake
      account: "{{ env_var('SNOWFLAKE_ACCOUNT') }}"
      user: "{{ env_var('SNOWFLAKE_USER') }}"
      authenticator: externalbrowser      # SSO; avoids storing a password
      role: TRANSFORMER_DEV
      database: ANALYTICS_DEV
      warehouse: TRANSFORMING_XS
      schema: dbt_priya             # personal dev schema — one per developer
      threads: 4
    prod:
      type: snowflake
      account: "{{ env_var('SNOWFLAKE_ACCOUNT') }}"
      user: "{{ env_var('SNOWFLAKE_USER') }}"
      private_key_path: "{{ env_var('SNOWFLAKE_KEY_PATH') }}"   # key-pair auth for CI
      role: TRANSFORMER
      database: ANALYTICS
      warehouse: TRANSFORMING_L
      schema: analytics
      threads: 12
```

- **Personal dev schemas.** Every developer builds into `dbt_<name>` so nobody overwrites
  anyone. This is the single most important dev-environment convention.
- **`threads`** is per-target. Raise it until the warehouse becomes the bottleneck; 4–8 in
  dev, 8–16 in prod is typical. Too many threads on a small warehouse queues rather than
  parallelizes.
- **`env_var('X')`** fails the run if unset — that is the desired behavior for a secret.
  `env_var('X', 'default')` supplies a fallback for non-secrets.
- **Custom schema naming.** dbt's default generates `<target_schema>_<custom_schema>`.
  Almost every team overrides `generate_schema_name` to use the custom schema directly in
  prod and the personal schema in dev:

```sql
-- macros/generate_schema_name.sql
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set default_schema = target.schema -%}
    {%- if target.name == 'prod' and custom_schema_name is not none -%}
        {{ custom_schema_name | trim }}
    {%- else -%}
        {{ default_schema }}
    {%- endif -%}
{%- endmacro %}
```

  The `target.name == 'prod'` test is load-bearing, not decoration. Returning the custom
  schema for every target is only safe where each environment is a separate database; in a
  shared one it means a laptop `dbt build` overwrites production's `marts`. If several
  environments each need verbatim names, make the isolation an explicit per-target opt-in
  and verify it, as in
  [the worked example](../../../use-cases/example-order-revenue-mart/dbt_project/macros/generate_schema_name.sql).

## Directory layout

```
models/
  staging/
    shopify/
      _shopify__sources.yml       # source definitions + freshness
      _shopify__models.yml        # descriptions + tests for these staging models
      stg_shopify__orders.sql
      stg_shopify__customers.sql
    stripe/
      ...
  intermediate/
    finance/
      _int_finance__models.yml
      int_orders_joined_to_payments.sql
  marts/
    finance/
      _finance__models.yml
      fct_orders.sql
      dim_customers.sql
    metricflow_time_spine.sql
  semantic/
    _semantic_models.yml
    _metrics.yml
macros/
snapshots/
seeds/
tests/                            # singular tests
analyses/                         # compiled but never run — scratch SQL, versioned
```

The leading underscore on YAML files sorts them to the top of the directory listing. One
YAML file per directory beats one giant `schema.yml`, and beats one YAML per model (which
makes cross-model tests awkward to place).

## Packages

```yaml
# packages.yml
packages:
  - package: dbt-labs/dbt_utils
    version: [">=1.3.0", "<2.0.0"]
  - package: calogica/dbt_expectations
    version: [">=0.10.0", "<0.11.0"]
  - package: dbt-labs/codegen
    version: [">=0.13.0", "<0.14.0"]
  - package: dbt-labs/audit_helper
    version: [">=0.12.0", "<0.13.0"]
  - git: "https://github.com/example/internal-dbt-macros.git"
    revision: v2.1.0              # a tag or SHA, never a branch
  - local: ../shared_transforms
```

```bash
dbt deps                          # installs into dbt_packages/; run before anything in CI
```

| Package | Use it for |
|---|---|
| `dbt_utils` | `generate_surrogate_key`, `date_spine`, `star`, `union_relations`, `unique_combination_of_columns`, `accepted_range`, `recency`, `equality` |
| `dbt_expectations` | Great-Expectations-style tests: distribution, regex, row-count between, column-type |
| `codegen` | Generate `sources.yml`, staging model SQL, and base `schema.yml` from the warehouse — huge time saver on a new source |
| `audit_helper` | `compare_relations` / `compare_all_columns` — the tool for proving a refactor is equivalent |
| `dbt_project_evaluator` | dbt Labs' own best-practice checks, run as models against your manifest |
| `elementary` | Anomaly detection and test-result history, self-hosted on Core |

**Version-range every package**, and commit `package-lock.yml` so CI resolves the same
versions you did.

Bootstrapping a new source with `codegen` (this is the fastest legitimate shortcut in dbt):

```bash
dbt run-operation generate_source --args '{"schema_name": "shopify", "database_name": "raw"}'
dbt run-operation generate_base_model --args '{"source_name": "shopify", "table_name": "orders"}'
dbt run-operation generate_model_yaml --args '{"model_names": ["stg_shopify__orders"]}'
```

Treat the output as a first draft — it gives you every column, and you supply the grain,
the descriptions, and the tests.

## Documentation site

```bash
dbt docs generate                 # writes target/catalog.json + the static site
dbt docs serve --port 8080        # local browser: DAG, lineage, descriptions, sources
```

`docs generate` queries the warehouse's information schema to build `catalog.json`, so it
needs a live connection and is slower than `dbt parse`. `--no-compile` skips recompiling if
you only need the catalog refreshed.

On dbt Core there is no hosted docs site. The usual pattern is a CI job that runs
`dbt docs generate` against prod and publishes `target/index.html`, `manifest.json`, and
`catalog.json` to S3/GCS behind SSO.

## Looking up dbt documentation

There is no offline docs bundle. When you need authoritative syntax:

1. **`dbt --help` and `dbt <command> --help`** — the definitive flag list for *your*
   installed version, which is more reliable than any web page for version-specific flags.
2. **The manifest schema** — `target/manifest.json` shows exactly which configs dbt
   actually resolved for a node. `dbt ls --select <model> --output json` is the fast form.
3. **The installed package source** — `dbt_packages/dbt_utils/macros/` is the real
   definition of any `dbt_utils` macro, and it is on your disk.
4. **docs.getdbt.com** via WebFetch for concepts and YAML spec. Always check the version
   selector: syntax like `unit_tests:`, `microbatch`, and `time_spine:` is version-gated,
   and answering from the wrong version is the most common failure here.
5. **The adapter's repo** for warehouse-specific configs — `dbt-snowflake`,
   `dbt-bigquery`, etc. document their own config keys, which are not in the core docs.

State the dbt version you are answering for. "This works in 2.0" is a useful answer;
"this works" is not.

## dbt MCP server on dbt Core

The `dbt-mcp` server exposes dbt to an agent as tools. On dbt Core it runs locally against
your project — the CLI tools work; the Cloud-only tool groups (Discovery API, Semantic
Layer API, Cloud jobs) do not.

```bash
uvx dbt-mcp        # or: pipx install dbt-mcp
```

```json
{
  "mcpServers": {
    "dbt": {
      "command": "uvx",
      "args": ["dbt-mcp"],
      "env": {
        "DBT_PROJECT_DIR": "/abs/path/to/analytics",
        "DBT_PATH": "/abs/path/to/.venv/bin/dbt",
        "DBT_PROFILES_DIR": "/Users/you/.dbt",
        "DISABLE_DBT_CLI": "false",
        "DISABLE_SEMANTIC_LAYER": "true",
        "DISABLE_DISCOVERY": "true",
        "DISABLE_ADMIN_API": "true"
      }
    }
  }
}
```

- Paths must be **absolute**; a relative `DBT_PROJECT_DIR` is the most common setup failure.
- `DBT_PATH` must point at the venv's `dbt`, not a system one.
- Disable the Cloud tool groups explicitly on Core — otherwise the server tries to
  authenticate against dbt Cloud and errors on startup.
- This is optional. Every capability is reachable by running `dbt` through Bash; MCP just
  makes it structured.

## `.gitignore`

```
target/
dbt_packages/
logs/
.user.yml
profiles.yml
.env
```

Commit `package-lock.yml`. Never commit `target/` — but **do** archive production
`manifest.json` / `run_results.json` / `sources.json` as CI artifacts, because slim CI,
freshness monitoring, and breaking-change detection all read them.

## Verification checklist

- [ ] `dbt debug` passes for every target
- [ ] `dbt deps` succeeds and `package-lock.yml` is committed
- [ ] `dbt parse` succeeds
- [ ] `dbt build --select stg_*` builds into a personal dev schema, not a shared one
- [ ] `dbt docs generate && dbt docs serve` renders the DAG
- [ ] `require-dbt-version` is set and CI pins the same versions
- [ ] No credentials in the repo; every secret comes from `env_var()`
- [ ] Snapshots write to a shared, non-environment-suffixed schema

## Troubleshooting

| Symptom | Cause |
|---|---|
| `Could not find profile named 'X'` | `profile:` in `dbt_project.yml` does not match the key in `profiles.yml` |
| `Env var required but not provided` | The variable is unset in this shell/CI context — intended behavior for a secret |
| `Runtime Error ... Database Error` on `dbt debug` | Credentials, network, or role. The adapter's error text names which |
| Models build into the wrong schema | dbt concatenates `<target_schema>_<custom_schema>` by default; override `generate_schema_name` |
| `dbt deps` resolves different versions than a teammate | `package-lock.yml` not committed |
| `dbt` command not found after install | Wrong venv activated, or installed with a different Python |
| Everything is slow on a tiny project | `threads: 1`, or a suspended warehouse resuming on every query |

Next: [analytics-request-framing](../analytics-request-framing/SKILL.md).
