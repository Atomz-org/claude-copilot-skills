# Warehouse Platform Notes

Adapter-specific configs, dialect differences, and the traps that only bite on one platform.

## Quick comparison

| | Snowflake | BigQuery | Databricks | Postgres | Redshift | DuckDB |
|---|---|---|---|---|---|---|
| Adapter | `dbt-snowflake` | `dbt-bigquery` | `dbt-databricks` | `dbt-postgres` | `dbt-redshift` | `dbt-duckdb` |
| Default incremental | `merge` | `merge` | `merge` | `delete+insert` | `delete+insert` | `delete+insert` |
| Best for large tables | `merge` + cluster | `insert_overwrite` + partition | `merge` + liquid clustering | `delete+insert` + index | `delete+insert` + sort/dist | n/a |
| Physical layout | `cluster_by` | `partition_by` + `cluster_by` | `partition_by` / liquid | `indexes` | `dist` + `sort` | none |
| Identifier case | uppercases unquoted | case-sensitive | lowercases | lowercases | lowercases | case-insensitive |
| `qualify` | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| Safe cast | `try_cast` | `safe_cast` | `try_cast` | none | none | `try_cast` |
| Materialized view | dynamic tables | materialized views | streaming tables | materialized views | materialized views | — |
| Billing | compute-second | bytes scanned | compute-second (DBU) | infra | infra / RPU | free |

## Snowflake

```sql
{{ config(
    materialized='incremental',
    unique_key='order_id',
    incremental_strategy='merge',
    cluster_by=['ordered_date'],
    transient=true,
    snowflake_warehouse='TRANSFORMING_L',
    query_tag='dbt:fct_orders',
    automatic_clustering=true,
    copy_grants=true
) }}
```

```yaml
# profiles.yml
type: snowflake
account: "{{ env_var('SNOWFLAKE_ACCOUNT') }}"
authenticator: externalbrowser         # SSO for dev
private_key_path: "{{ env_var('SF_KEY') }}"   # key-pair for CI/prod
role: TRANSFORMER
warehouse: TRANSFORMING_XS
database: ANALYTICS
schema: dbt_priya
threads: 8
client_session_keep_alive: false
query_tag: dbt
reuse_connections: true
```

**Traps:**

- **Unquoted identifiers uppercase.** `select order_id` returns a column named `ORDER_ID`.
  Unit-test fixtures and contract `data_type` declarations both trip on this.
- **`varchar` defaults to `varchar(16777216)`** — declare that in a contract, not bare
  `varchar`.
- **Date string literals are varchar**, not dates. `'2024-01-15' = ordered_date` may fail to
  compare. Cast explicitly.
- **Clustering has an ongoing maintenance cost.** Worth it above roughly 1 TB; below that
  micro-partition pruning generally handles it.
- **`transient=true`** removes Fail-safe storage on rebuildable models — real savings.
- **Auto-suspend at 60s** so idle warehouse time is not billed.
- **Query Profile** is the diagnostic: "Bytes spilled to remote storage" means the warehouse
  is too small; a low pruning ratio means clustering or the filter is wrong.

**Dynamic tables** replace materialized views for anything non-trivial:

```sql
{{ config(materialized='dynamic_table', target_lag='1 hour',
          snowflake_warehouse='TRANSFORMING', on_configuration_change='apply') }}
```

## BigQuery

```sql
{{ config(
    materialized='incremental',
    incremental_strategy='insert_overwrite',
    partition_by={'field': 'ordered_date', 'data_type': 'date', 'granularity': 'day'},
    cluster_by=['customer_id', 'order_status'],
    require_partition_filter=true,
    partition_expiration_days=1095,
    labels={'domain': 'finance', 'cost_center': 'analytics'}
) }}
```

```yaml
type: bigquery
method: oauth                          # or service-account, service-account-json
project: my-gcp-project
dataset: dbt_priya
location: US
threads: 12
priority: interactive
maximum_bytes_billed: 500000000000     # a hard guardrail against runaway queries
job_execution_timeout_seconds: 600
job_retries: 1
```

**Traps:**

- **Strictest type system of any adapter.** `INT64` vs `NUMERIC` vs `FLOAT64` must match
  exactly — no implicit casts. Unit-test fixtures need `format: sql` far more often here.
- **`DATE` / `DATETIME` / `TIMESTAMP` are three different types** and do not compare.
- **You are billed for bytes scanned**, so partitioning is not an optimization, it is the
  cost model. `require_partition_filter=true` is a high-value guardrail.
- **`insert_overwrite` is dramatically cheaper than `merge`** on large partitioned tables.
- **Cluster on up to 4 columns**, most-filtered first.
- **`maximum_bytes_billed`** stops one bad query from costing thousands.
- **`STRUCT` and `ARRAY`** columns require `format: sql` in unit tests.
- **`INFORMATION_SCHEMA.JOBS`** gives per-query bytes billed — the ground truth for cost
  attribution.

Partition granularity: `hour`, `day`, `month`, `year`, or `range_bucket` for integers.

## Databricks / Spark

```sql
{{ config(
    materialized='incremental',
    file_format='delta',
    incremental_strategy='merge',
    unique_key='order_id',
    partition_by=['ordered_date'],
    liquid_clustering=true,
    clustered_by=['customer_id'],
    tblproperties={'delta.autoOptimize.optimizeWrite': 'true'}
) }}
```

```yaml
type: databricks
host: "{{ env_var('DATABRICKS_HOST') }}"
http_path: "{{ env_var('DATABRICKS_HTTP_PATH') }}"
token: "{{ env_var('DATABRICKS_TOKEN') }}"
catalog: analytics                     # Unity Catalog
schema: dbt_priya
threads: 8
```

**Traps:**

- **Small files kill performance.** Partitioning on a high-cardinality column produces
  thousands of tiny files. Prefer liquid clustering.
- **`OPTIMIZE` and `VACUUM` must be scheduled** — via post-hook or a separate job. Delta
  tables degrade without compaction.
- **`DECIMAL` scale must match exactly** in unit test fixtures.
- **Nulls in a `union all` need `cast(null as <type>)`** — untyped nulls break fixtures.
- **`file_format='delta'`** is required for `merge`.
- Use **`dbt-databricks`**, not `dbt-spark`, on Databricks — it supports Unity Catalog,
  liquid clustering, and constraints.

## Postgres

```sql
{{ config(
    materialized='table',
    indexes=[
      {'columns': ['order_id'], 'unique': True},
      {'columns': ['ordered_at']},
      {'columns': ['customer_id', 'ordered_at'], 'type': 'btree'}
    ]
) }}
```

```yaml
type: postgres
host: "{{ env_var('PG_HOST') }}"
port: 5432
user: "{{ env_var('PG_USER') }}"
password: "{{ env_var('PG_PASSWORD') }}"
dbname: analytics
schema: dbt_priya
threads: 4
keepalives_idle: 0
search_path: public
```

**Traps:**

- **No `qualify`.** Rewrite `qualify row_number() over (...) = 1` as a subquery with a
  `where`. This is the most common porting failure into Postgres.
- **Indexes are the only lever** — no columnar pruning. Index join and filter columns.
- **`work_mem`** — a sort spilling to disk is often the entire performance problem.
- **`delete+insert` is the default** incremental strategy; `merge` is unavailable on older
  versions.
- **No `try_cast`.** Use a `case` with a regex guard.
- `EXPLAIN (ANALYZE, BUFFERS)` on the compiled SQL is the diagnostic.
- Excellent for a small warehouse or for local development; stops scaling somewhere around a
  few hundred GB of fact data.

## Redshift

```sql
{{ config(
    materialized='table',
    dist='customer_id',       -- co-locate joined rows
    sort=['ordered_at'],
    sort_type='compound'      -- compound | interleaved
) }}
```

```yaml
type: redshift
host: "{{ env_var('REDSHIFT_HOST') }}"
port: 5439
user: "{{ env_var('REDSHIFT_USER') }}"
password: "{{ env_var('REDSHIFT_PASSWORD') }}"
dbname: analytics
schema: dbt_priya
threads: 4
ra3_node: true
```

**Traps:**

- **`dist` is the biggest lever.** `dist` on the join key eliminates data movement;
  `dist='all'` replicates small dimensions to every node.
- **`sort` on the filter column** so zone maps skip blocks.
- **`VACUUM` and `ANALYZE`** after large loads, or the planner uses stale statistics.
- **`varchar(256)` is the default** — long strings truncate silently, which bites in unit-test
  fixtures.
- **No `qualify`.**
- **`merge` requires Redshift with a recent engine and dbt 1.6+**; `delete+insert` otherwise.
- Boolean handling is quirky — use `true`/`false` literals, never `1`/`0`.

## DuckDB

```yaml
type: duckdb
path: ./analytics.duckdb        # or ':memory:'
threads: 4
extensions: [httpfs, parquet]
```

**Best for:** local development and testing, CI without a cloud warehouse, and small
projects. The most permissive type system of any adapter — unit tests that fail on BigQuery
usually pass here, which makes it a good place to *develop* tests before running them against
the real adapter.

Not a production warehouse for a team — single-writer, no concurrency model.

## Trino / Athena

```yaml
type: trino
host: trino.example.com
port: 443
catalog: hive
schema: dbt_priya
threads: 8
```

Federated queries across catalogs. Materialization support is thinner —
`dbt-athena-community` supports `table`, `incremental` (append/insert_overwrite), and views;
`merge` requires Iceberg tables. Check the adapter's docs before assuming a strategy exists.

## Writing one project that runs on all of them

The worked example runs unmodified on DuckDB, BigQuery, and Snowflake. Five things make
that possible, and each of them is a bug you would otherwise find on the *other*
warehouse, usually in production.

### 1. Develop locally on DuckDB

```bash
pip install 'dbt-core~=1.9.0' 'dbt-duckdb~=1.9.0'
dbt build --target duckdb_dev      # embedded file, no server, no credentials
```

An embedded database makes the whole test loop — seeds, models, data tests, unit tests,
snapshots, all the artifact analyzers — runnable on a laptop and in CI with no warehouse
account. Use it for logic; use the real warehouse for anything about cost, scale, or
adapter-specific SQL.

### 2. Never hardcode an incremental strategy

`merge` does not exist on DuckDB, Postgres, or Redshift. Worse, the failure appears on the
**second** run — the first is a plain create that never exercises the strategy — so a
hardcoded `merge` is a portability bug with a one-run delay on it.

```sql
{% raw %}{% macro incremental_upsert_strategy() %}
    {% if target.type in ('snowflake', 'bigquery', 'databricks', 'spark') %}
        {{ return('merge') }}
    {% else %}
        {{ return('delete+insert') }}
    {% endif %}
{% endmacro %}{% endraw %}
```

### 3. Clustering and partitioning are not the same concept

An unsupported config key is a hard error, not a warning. Return the right keys per
adapter, and an empty dict where the concept does not exist:

| Platform | Config |
|---|---|
| Snowflake | `cluster_by=[...]` |
| BigQuery | `partition_by={...}` + `cluster_by=[...]` (max 4) |
| Databricks | `file_format='delta'`, `partition_by` |
| DuckDB, Postgres | nothing — return `{}` |

### 4. Cast every aggregate if the model has an enforced contract

Contracts compare **exact** warehouse types, and aggregates widen differently everywhere:

| Expression | DuckDB | BigQuery | Snowflake |
|---|---|---|---|
| `count(*)` | `BIGINT` | `INT64` | `NUMBER(38,0)` |
| `sum(numeric(28,6))` | `DECIMAL(38,6)` | `NUMERIC` | `NUMBER(38,6)` |

So `cast(count(*) as {% raw %}{{ dbt.type_int() }}{% endraw %})`, not bare `count(*)`. An
uncast aggregate under a contract fails the build on whichever adapter you did not
develop on.

`numeric(28,6)` written literally is accepted by all three, which is why it is safe to
hardcode in a YAML property file — where project macros are unavailable anyway.

### 5. Use dbt's cross-database macros instead of dialect functions

| Do not write | Write |
|---|---|
| `dateadd(day, 1, x)` | `{% raw %}{{ dbt.dateadd('day', 1, 'x') }}{% endraw %}` |
| `datediff(...)` | `{% raw %}{{ dbt.datediff(...) }}{% endraw %}` |
| `x \|\| y` | `{% raw %}{{ dbt.concat(['x','y']) }}{% endraw %}` |
| `numeric` | `{% raw %}{{ dbt.type_numeric() }}{% endraw %}` |
| `cast(x as int)` on dirty data | `{% raw %}{{ dbt.safe_cast('x', api.Column.translate_type('integer')) }}{% endraw %}` |
| `md5(concat(...))` | `{% raw %}{{ dbt_utils.generate_surrogate_key([...]) }}{% endraw %}` |

Two Jinja traps that cost a build each:

- dbt's cross-database macros **emit text rather than returning a value**, so
  `{% raw %}{% set x = dbt.dateadd(...) %}{% endraw %}` captures nothing. Use the block
  form: `{% raw %}{% set x %}{{ dbt.dateadd(...) }}{% endset %}{% endraw %}`.
- **Jinja renders SQL comments.** A Jinja tag inside a `--` comment is evaluated, not
  ignored. And `--` inside a `config()` call is a syntax error, because that is Jinja,
  not SQL.

### Moving an existing project

| Step | What |
|---|---|
| 1 | Add the target to `profiles.yml`; `dbt debug --target <new>` |
| 2 | `dbt parse` — catches YAML and macro problems with no warehouse round-trip |
| 3 | `dbt compile --target <new>` — catches dialect problems without writing anything |
| 4 | `dbt build --target <new> --empty` — exercises DDL against zero rows |
| 5 | `dbt build --target <new>` twice — the second run is what tests the incremental path |
| 6 | Reconcile row counts and column sums old vs new with `audit_helper` |

Detail on step 6 in [migration_playbooks.md](migration_playbooks.md).

## Dialect differences

| Operation | Snowflake | BigQuery | Databricks | Postgres / Redshift |
|---|---|---|---|---|
| Date add | `dateadd(day,1,d)` | `date_add(d, interval 1 day)` | `date_add(d,1)` | `d + interval '1 day'` |
| Date diff | `datediff(day,a,b)` | `date_diff(b,a,day)` | `datediff(b,a)` | `b - a` |
| Date trunc | `date_trunc('month',d)` | `date_trunc(d, month)` | `date_trunc('month',d)` | `date_trunc('month',d)` |
| Concat | `\|\|` / `concat()` | `concat()` | `\|\|` | `\|\|` |
| Safe cast | `try_cast` | `safe_cast` | `try_cast` | — |
| Current time | `current_timestamp()` | `current_timestamp()` | `current_timestamp()` | `now()` |
| Regex match | `regexp_like` | `regexp_contains` | `rlike` | `~` |
| String split | `split_part` | `split(s,d)[offset(n)]` | `split_part` | `split_part` |
| Array agg | `array_agg` | `array_agg` | `collect_list` | `array_agg` |
| String agg | `listagg` | `string_agg` | `concat_ws` | `string_agg` |
| `qualify` | ✅ | ✅ | ✅ | ❌ |
| Semi-structured | `variant`, `:` path | `STRUCT`/`ARRAY`, dot | `MAP`/`STRUCT` | `jsonb` |

**Use dbt's cross-database macros instead of any of these.** That is what they are for:

```sql
{{ dbt.dateadd('day', -3, 'ordered_at') }}
{{ dbt.datediff('ordered_at', 'shipped_at', 'day') }}
{{ dbt.safe_cast('amount', api.Column.translate_type('numeric')) }}
{{ dbt.split_part('full_name', "' '", 1) }}
{{ dbt.listagg('product_name', "', '") }}
{{ dbt.type_numeric() }} {{ dbt.type_timestamp() }} {{ dbt.type_string() }}
```

For anything not covered, use `adapter.dispatch` rather than scattering
`{% if target.type == '...' %}` through models.

## Unit test type notes

The most platform-sensitive part of a dbt project. When a unit test fails with an
inexplicable comparison error, switch that input to `format: sql` and cast explicitly.

| Platform | The specific trap |
|---|---|
| Snowflake | date literals are varchar; numeric scale mismatches |
| BigQuery | no implicit casts at all; `DATE`/`DATETIME`/`TIMESTAMP` are distinct; nulls need explicit casts |
| Databricks | `DECIMAL` scale; untyped nulls in `union all` |
| Postgres | `numeric` vs `float8`; empty string is not null |
| Redshift | `varchar(256)` truncation; boolean literals |
| DuckDB | rarely a problem — good for developing tests |
