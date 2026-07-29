# Governance Reference — Contracts, Groups, Access, Versions

Full YAML spec for dbt Core's governance features, plus the multi-project patterns available
without dbt Cloud.

## Contracts

```yaml
models:
  - name: fct_orders
    config:
      contract: {enforced: true}
    columns:
      - name: order_id
        data_type: varchar              # MANDATORY for every column when enforced
        constraints:
          - type: not_null
          - type: primary_key
        data_tests: [unique, not_null]
      - name: customer_id
        data_type: varchar
        constraints:
          - type: foreign_key
            to: ref('dim_customers')
            to_columns: [customer_id]
      - name: order_amount_usd
        data_type: numeric(28,6)
        constraints:
          - type: check
            expression: "order_amount_usd >= 0"
      - name: ordered_at
        data_type: timestamp
```

Model-level constraints (composite keys):

```yaml
    constraints:
      - type: primary_key
        columns: [order_id, line_number]
      - type: check
        expression: "net_amount_usd <= gross_amount_usd"
        name: net_lte_gross
```

### Enforcement by warehouse

| Constraint | Postgres | Snowflake | BigQuery | Databricks | Redshift |
|---|---|---|---|---|---|
| `not_null` | enforced | enforced | enforced | enforced | enforced |
| `primary_key` | enforced | metadata | metadata | metadata (Unity) | metadata |
| `unique` | enforced | metadata | not supported | metadata | metadata |
| `foreign_key` | enforced | metadata | metadata | metadata | metadata |
| `check` | enforced | not supported | not supported | enforced | not supported |

"Metadata" means the warehouse records the constraint but never validates a row. **Always
keep the equivalent `data_tests`** — the test checks the data, the constraint documents the
schema. Treating a metadata-only `primary_key` as a uniqueness guarantee is a common and
expensive mistake.

### `data_type` mismatches

The most frequent contract failure. Build the model once, then read the real types from
`target/catalog.json` (after `dbt docs generate`) or `information_schema.columns`.

| Declared | Actual | Reason |
|---|---|---|
| `numeric` | `numeric(38,0)` | warehouse default precision |
| `varchar` | `varchar(16777216)` | Snowflake default max length |
| `string` | `text` / `varchar` | adapter alias |
| `int` | `bigint` / `int64` | integer width inference |
| `timestamp` | `timestamp_ntz` / `timestamp_tz` | timezone-awareness is part of the type |
| `float` | `double` / `float64` | same |

`scripts/schema_yml_generator.py --catalog target/catalog.json` pulls the real types in for
you.

### Where to enforce

Enforce at the **boundary** — any model with a consumer you cannot fix in the same PR:
another project, a BI dataset, a reverse-ETL sync, an ML feature pipeline, anything with an
SLA. Do not enforce on staging and intermediate; the YAML maintenance is real and there is no
boundary to protect.

## Groups

```yaml
groups:
  - name: finance
    owner:
      name: Finance Analytics
      email: finance-data@example.com
      slack: "#finance-data"
  - name: marketing
    owner: {name: Growth Analytics, email: growth-data@example.com}
```

```yaml
models:
  - name: fct_revenue
    config: {group: finance}
```

Or in `dbt_project.yml`:

```yaml
models:
  analytics:
    marts:
      finance:
        +group: finance
```

Groups do two things: they set `access: private` scope, and they name who gets paged. Fill in
a real email or channel — the alerting routes off it.

```bash
dbt build --select group:finance
```

## Access

```yaml
models:
  - name: fct_revenue
    config: {access: public}
  - name: int_revenue_allocated
    config: {access: private, group: finance}
```

| Access | Who may `ref` it |
|---|---|
| `private` | only models in the same `group` |
| `protected` | any model in this project (**the default**) |
| `public` | any model, including other projects |

`private` on intermediate models is the highest-value use of this feature — it stops another
team `ref`ing your internals and quietly making them load-bearing.

`public` is a promise. Pair it with `contract: {enforced: true}` and a version policy, or it
is a label rather than a commitment.

```bash
dbt ls --select access:public       # your actual API surface
```

## Versions

```yaml
models:
  - name: fct_orders
    latest_version: 2
    config:
      contract: {enforced: true}
      access: public
    columns:
      - name: order_id
        data_type: varchar
      - name: order_amount_usd
        data_type: numeric(28,6)
      - name: currency_code
        data_type: varchar
    versions:
      - v: 1
        defined_in: fct_orders_v1      # optional; defaults to fct_orders_v1.sql
        deprecation_date: 2026-09-30 00:00:00+00:00
        columns:
          - include: all
            exclude: [currency_code]
      - v: 2
        config:
          alias: fct_orders            # the unsuffixed relation name
```

Files: `fct_orders_v1.sql` and `fct_orders.sql` (the latest). `defined_in` overrides.

```sql
select * from {{ ref('fct_orders') }}          -- latest_version
select * from {{ ref('fct_orders', v=1) }}     -- pinned
```

Column inheritance in a version block:

```yaml
columns:
  - include: all                    # all | all_columns | []
    exclude: [currency_code]
  - name: legacy_amount             # add a column unique to this version
    data_type: numeric(28,6)
```

**Always set `deprecation_date`.** dbt warns every consumer still `ref`ing a deprecated
version — that warning is the only mechanism that retires old versions. Without it, v1 lives
forever.

## Breaking changes

| Change | Breaking? | Action |
|---|---|---|
| Add a column | No | Ship it (update contract YAML if enforced) |
| Rename a column | **Yes** | Version, or coordinate every consumer in one PR |
| Change a data type | **Yes** — widening included, if a consumer casts | Version |
| Remove a column | **Yes** | Version with a `deprecation_date` |
| **Change the grain** | **Yes, and the worst kind** | Version, and notify consumers directly |
| Add a row-dropping filter | **Yes** in effect | Treat as a grain change |
| Narrow `access` | **Yes** for anything already `ref`ing it | Check the DAG first |
| Remove `contract: enforced` | **Yes** — the promise is withdrawn | Announce it |
| Change `materialized` | Usually not | Check for consumers depending on table-vs-view behavior |

**The grain change is the dangerous one:** the column list is identical, every contract
passes, every test passes, and every downstream number is silently wrong. Nothing in dbt
catches it. Treat it as breaking even though nothing errors.

dbt itself raises a breaking-change error at parse time when a contracted model's columns
change without a version bump. It does **not** catch grain changes, access narrowing, or
impact on non-contracted models — that is what the detector script is for.

```bash
python scripts/contract_breaking_change_detector.py \
    --base prod/manifest.json --head target/manifest.json --strict
```

## Multi-project on dbt Core

Cross-project `ref()` requires the Cloud Discovery API. Three Core patterns achieve the same
separation.

### 1. One project, groups and access

Keep one repo. `groups` for ownership, `access: private` for boundaries, model paths split by
domain, `--select` per team in CI.

**Choose when** teams deploy on a shared cadence and the DAG is under ~500 models. Simplest
by a wide margin, and the DAG stays whole.

### 2. Upstream as an installed package

```yaml
# downstream packages.yml
packages:
  - git: "https://github.com/example/core-analytics.git"
    revision: v2.4.0        # a tag — never a branch
```

```sql
select * from {{ ref('core_analytics', 'fct_orders') }}
```

The upstream models compile into the downstream project, so `ref` works normally. The catch:
downstream **rebuilds** them unless you disable them:

```yaml
# downstream dbt_project.yml
models:
  core_analytics:
    +enabled: false
    marts:
      +enabled: true        # only the marts you actually consume
```

**Choose when** upstream ownership is clear and downstream can pin a version. The real
benefit is that version bumps are explicit — downstream chooses when to take a breaking
change.

### 3. Upstream's tables as sources

```yaml
sources:
  - name: core_analytics
    database: ANALYTICS_PROD
    schema: marts
    tables:
      - name: fct_orders
        description: >
          Owned by Core Analytics. Contract: docs/contracts/fct_orders.md.
          Grain: one row per order. Breaking changes announced in #core-analytics
          with 30 days notice.
        loaded_at_field: _dbt_updated_at
        freshness:
          warn_after:  {count: 2, period: hour}
          error_after: {count: 6, period: hour}
        columns:
          - name: order_id
            data_tests: [unique, not_null]
```

**Choose when** teams deploy independently or have separate warehouses/roles. Costs you the
unified DAG — the downstream project cannot see upstream lineage and impact analysis becomes
manual. Compensate with: a freshness block on every such source, tests on the incoming keys,
a written contract document, and the upstream team running the breaking-change detector.

### Comparison

| | One project | Package | Source |
|---|---|---|---|
| Unified DAG | yes | yes | no |
| Independent deploys | no | yes | yes |
| Automatic impact analysis | yes | yes | **no** |
| Version pinning | n/a | yes | manual |
| Setup cost | none | low | low |
| Ongoing coordination cost | low | medium | **high** |

Start at (1). Move to (2) when deploy cadences genuinely diverge. Use (3) only when separate
warehouses or security boundaries force it.

## Grants

```yaml
models:
  - name: fct_orders
    config:
      grants:
        select: ['REPORTER', 'ANALYST']
```

```yaml
# dbt_project.yml — project-wide defaults
models:
  analytics:
    marts:
      +grants:
        select: ['REPORTER']
      finance:
        +grants:
          select: ['+FINANCE_ANALYST']    # `+` appends instead of replacing
```

Declarative and reconciled by dbt on every build — strictly better than a grant post-hook,
which drifts.

## Publishing a contract

Whatever the pattern, an external consumer needs this written down — in the model
description, a `docs` block, or `docs/contracts/<model>.md`:

- **Grain** — one sentence.
- **Columns** — name, type, meaning, nullability.
- **Freshness** — when it updates and the SLA.
- **Stability** — `public`? versioned? what notice period for breaking changes?
- **Owner** — a person or a channel, not "the data team".
- **How breaking changes are announced**, and how far in advance.

A table name handed over without these is not a contract; it is a dependency someone will be
surprised by.

## Anti-patterns

- Contracts on every model — enormous YAML maintenance, no boundary benefit.
- `access: public` with no contract and no version policy.
- Versioning additive changes.
- No `deprecation_date`, so v1 never retires.
- Treating a metadata-only `primary_key` as a uniqueness guarantee.
- Splitting into five projects before the DAG needs it — all the coordination cost, none of
  the benefit.
- Changing the grain without versioning because "the columns didn't change".
- A `group` whose `owner` email does not resolve to a real person or channel.
