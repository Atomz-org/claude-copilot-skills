---
name: dbt-mesh-governance
description: Govern a dbt Core project's boundaries — enforced model contracts with data types and constraints, groups and owners, access modifiers (private/protected/public), model versions with deprecation dates, and multi-project patterns on dbt Core (packages, artifact sharing, cross-project refs). Use when a model has consumers outside the project, when a schema change might break someone, when splitting a monolith project, when asked "how do I stop people breaking this model", or "what breaks if I change this".
---

# Governance and Multi-Project (dbt Mesh on Core)

Governance is how a model gets consumers who are not you. Without it, every change is a
guess about who might break.

**dbt Core scope.** Contracts, groups, `access:`, and versions are all core dbt features
and work fully on Core. What is Cloud-only is the *cross-project `ref`* mechanism, which
resolves another project's public models through the Cloud Discovery API. On Core you get
the same outcome through packages or a shared warehouse layer — covered at the bottom.

## Contracts

A contract makes dbt verify the model's shape at build time and fail the **build**, not the
dashboard.

```yaml
models:
  - name: fct_orders
    config:
      contract: {enforced: true}
    columns:
      - name: order_id
        data_type: varchar              # mandatory for EVERY column once enforced
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
      - name: ordered_at
        data_type: timestamp
```

### When to enforce

Enforce on any model with a consumer you **cannot fix in the same pull request**:

- another team's or another project's models;
- a BI tool's semantic/dataset layer;
- a reverse-ETL sync into a SaaS tool;
- an ML feature pipeline;
- anything with an SLA attached.

Do **not** enforce on staging and intermediate models. The cost is real — every additive
column change now needs a YAML edit — and the benefit only exists at a boundary.

### Constraint enforcement varies by warehouse

| Constraint | Postgres | Snowflake | BigQuery | Databricks | Redshift |
|---|---|---|---|---|---|
| `not_null` | enforced | enforced | enforced | enforced | enforced |
| `primary_key` | enforced | metadata only | metadata only | metadata only (Unity) | metadata only |
| `unique` | enforced | metadata only | not supported | metadata only | metadata only |
| `foreign_key` | enforced | metadata only | metadata only | metadata only | metadata only |
| `check` | enforced | not supported | not supported | enforced | not supported |

"Metadata only" means the warehouse accepts and records the constraint but never validates
a row against it. **Always keep the equivalent `data_tests`** — the test checks the data,
the constraint documents the schema. Treating a metadata-only `primary_key` as a guarantee
is a common and expensive mistake.

### `data_type` is the usual failure

The contract compares your declared type against what the warehouse actually produces.
Mismatches that bite:

| Declared | Actual | Why |
|---|---|---|
| `numeric` | `numeric(38,0)` | Warehouse default precision differs from yours |
| `varchar` | `varchar(16777216)` | Snowflake's default max length |
| `string` | `text` / `varchar` | Adapter-specific alias |
| `int` | `bigint` / `int64` | Integer width inference |
| `timestamp` | `timestamp_ntz` / `timestamp_tz` | Timezone-awareness is part of the type |
| `float` | `double` / `float64` | Same |

Fastest fix: build the model once, then read the real types out of `target/catalog.json`
(after `dbt docs generate`) or `information_schema.columns`, and paste those in.
`schema_yml_generator.py` does this for you when given a catalog.

## Groups and access

```yaml
# models/marts/finance/_finance__models.yml
groups:
  - name: finance
    owner:
      name: Finance Analytics
      email: finance-data@example.com
      slack: "#finance-data"

models:
  - name: fct_revenue
    config:
      group: finance
      access: public
      contract: {enforced: true}
  - name: int_revenue_allocated
    config:
      group: finance
      access: private          # only finance-group models may ref it
```

| Access | Who may `ref` it | Use for |
|---|---|---|
| `private` | only models in the same `group` | intermediate models, internal helpers |
| `protected` | any model in this project (the default) | ordinary marts |
| `public` | any model, including other projects | the deliberate, documented API surface |

- **`public` is a promise.** Pair it with `contract: {enforced: true}` and a version policy,
  or it is a label rather than a commitment.
- **`private` on intermediate models is the highest-value use of this feature.** It stops
  another team `ref`ing your internals and quietly making them load-bearing.
- **Group ownership is who gets paged.** Fill in a real email or channel.

## Versions

Version a model when you must break its shape while a consumer still reads the old one.

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
        deprecation_date: 2026-09-30 00:00:00+00:00
        columns:
          - include: all
            exclude: [currency_code]      # v1 predates multi-currency
      - v: 2
```

Files: `fct_orders_v1.sql` holds v1; the unsuffixed `fct_orders.sql` is the latest. Set
`defined_in:` to override that.

```sql
select * from {{ ref('fct_orders') }}          -- resolves to latest_version (2)
select * from {{ ref('fct_orders', v=1) }}     -- pinned
```

**Always set `deprecation_date`.** dbt warns every consumer still `ref`ing a deprecated
version, and that warning is the only mechanism that actually retires old versions. Without
it, v1 lives forever.

Version only for **breaking** changes:

| Change | Breaking? | Action |
|---|---|---|
| Add a column | No | Ship it (update contract YAML if enforced) |
| Rename a column | **Yes** | Version, or coordinate every consumer in one PR |
| Change a data type | **Yes** — widening included, if a consumer casts | Version |
| Remove a column | **Yes** | Version with a `deprecation_date` |
| **Change the grain** | **Yes, and worst of all** | Version, and notify consumers directly |
| Narrow `access` | **Yes** for anything already `ref`ing it | Check the DAG first |
| Add a filter that drops rows | **Yes** in effect | Treat as a grain change |

A grain change is the dangerous one: the column list is identical, every contract passes,
every test passes, and every downstream number is silently wrong. Treat it as breaking even
though nothing errors.

## Detecting breaking changes

Run this in CI on every PR:

```bash
python scripts/contract_breaking_change_detector.py \
    --base prod/manifest.json --head target/manifest.json --strict
```

It diffs two manifests for: removed models, removed columns, changed `data_type` on a
contracted model, contracts disabled, `access` narrowed, `latest_version` changes, removed
versions, and public models losing their contract. `--strict` exits 1 so the PR gate fails.

dbt itself also enforces this: changing a contracted model's columns without a version bump
raises a **breaking-change error** at parse time. The script catches the cases dbt does not —
grain-affecting changes, access narrowing, and impact on non-contracted models.

Pair it with blast radius:

```bash
python scripts/model_dependency_analyzer.py --manifest target/manifest.json \
    --model fct_orders --direction down --depth 99
```

## Multi-project on dbt Core

Cross-project `ref` needs the Cloud Discovery API. On Core, three patterns get you the same
separation. Pick by how tightly the teams are coupled.

### 1. One project, groups and access (best default)

Keep one repo. Use `groups` for ownership and `access: private` to enforce boundaries.
Split model paths by domain and use `--select` per team in CI.

**Choose when** teams deploy on a shared cadence and the DAG is under ~500 models. Simplest
by a wide margin, and the DAG stays whole.

### 2. Upstream project as an installed package

The downstream project installs the upstream as a package. `ref()` works normally because
the upstream models are compiled into the downstream project.

```yaml
# packages.yml in the downstream project
packages:
  - git: "https://github.com/example/core-analytics.git"
    revision: v2.4.0        # a tag — never a branch
```

```sql
select * from {{ ref('core_analytics', 'fct_orders') }}   -- two-arg ref: package, model
```

**Choose when** upstream ownership is clear and downstream can pin a version. The catch is
that downstream **rebuilds** the upstream models into its own schema unless you disable
them and point at the production relations:

```yaml
# downstream dbt_project.yml — consume, don't rebuild
models:
  core_analytics:
    +enabled: false         # disable everything from the package...
    marts:
      +enabled: true        # ...except the marts you actually need
```

Version bumps are explicit (`revision:`), which is the real benefit: the downstream team
chooses when to take a breaking change.

### 3. Source-of-another-project (loosest)

The downstream project declares the upstream's production tables as `sources:`.

```yaml
sources:
  - name: core_analytics
    database: ANALYTICS_PROD
    schema: marts
    tables:
      - name: fct_orders
        description: >
          Owned by the Core Analytics team. Contract: docs/contracts/fct_orders.md.
          Grain: one row per order. Breaking changes announced in #core-analytics.
        loaded_at_field: _dbt_updated_at
        freshness:
          error_after: {count: 6, period: hour}
```

**Choose when** teams deploy independently and have separate warehouses or roles. Costs you
the unified DAG — the downstream project cannot see upstream lineage, and impact analysis
must be manual. Compensate with: a freshness block on every such source, a written contract
document, and the upstream team running the breaking-change detector before they ship.

### Comparison

| | One project | Package | Source |
|---|---|---|---|
| Unified DAG | yes | yes | no |
| Independent deploys | no | yes | yes |
| Automatic impact analysis | yes | yes | **no** |
| Version pinning | n/a | yes | manual |
| Setup cost | none | low | low |
| Ongoing coordination cost | low | medium | **high** |

Start at (1). Move to (2) when deploy cadences genuinely diverge. Use (3) only when
separate warehouses or security boundaries force it.

## Publishing a contract for a consumer

Whatever the pattern, an external consumer needs this written down — in the model
description, a `docs` block, or a `docs/contracts/` markdown file:

- **Grain** — one sentence.
- **Columns** — name, type, meaning, nullability.
- **Freshness** — when it updates, and the SLA.
- **Stability** — is it `public`? versioned? what is the deprecation notice period?
- **Owner** — a person or a channel, not "the data team".
- **How breaking changes are announced** — and how far in advance.

A table name handed over without these is not a contract; it is a dependency somebody will
be surprised by.

## Anti-patterns

- `contract: {enforced: true}` on every model. Enormous YAML maintenance, no boundary benefit.
- `access: public` with no contract and no version policy — a promise nobody intends to keep.
- Versioning for additive changes. Adding a column is not breaking; versioning it doubles
  the maintenance for nothing.
- No `deprecation_date`, so v1 lives forever and every consumer stays on it.
- Treating a metadata-only `primary_key` constraint as a uniqueness guarantee.
- Splitting one project into five before the DAG is even large enough to need it — you buy
  every coordination cost and none of the benefit.
- Changing a model's grain without versioning, because "the columns didn't change".

Reference: [references/dbt_mesh_governance.md](../../../references/dbt_mesh_governance.md).
