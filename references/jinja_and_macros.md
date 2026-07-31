# Jinja, Macros, and Packages

The templating layer, the cross-database macros that make a project portable, and the
packages worth installing.

## Jinja basics in dbt

```sql
{{ ... }}     expression — renders a value into the SQL
{% ... %}     statement — control flow, no output
{# ... #}     comment — never rendered
{{- ... -}}   whitespace control — strips surrounding whitespace
```

### The context

| Variable | Is |
|---|---|
| `{{ this }}` | the current model's relation — `database.schema.identifier` |
| `{{ ref('m') }}` | another model's relation; creates the DAG edge |
| `{{ ref('pkg','m') }}` | a model from an installed package |
| `{{ ref('m', v=2) }}` | a specific model version |
| `{{ source('s','t') }}` | a source relation; creates the DAG edge |
| `{{ var('x', 'default') }}` | a project or CLI var |
| `{{ env_var('X') }}` | an environment variable — fails if unset |
| `{{ target }}` | `.name`, `.schema`, `.database`, `.type`, `.threads` |
| `{{ is_incremental() }}` | true when the model exists and this is not a full refresh |
| `{{ execute }}` | false during parsing, true during execution |
| `{{ run_started_at }}` | a datetime, consistent across the whole invocation |
| `{{ invocation_id }}` | UUID for this run — useful in audit columns |
| `{{ model }}` | this node's manifest entry |
| `{{ graph }}` | the whole manifest, at execution time |
| `{{ builtins }}` | the original `ref`/`source`/`config` when you override them |

### The two-pass problem

dbt **parses** the project first (building the DAG), then **executes**. During parsing,
`execute` is `false` and any warehouse query returns nothing. Anything introspective must be
guarded:

```sql
{% set statuses = [] %}
{% if execute %}
    {% set statuses = dbt_utils.get_column_values(ref('dim_status'), 'status_name') %}
{% endif %}

select
    order_id,
    {% for s in statuses %}
    sum(case when status = '{{ s }}' then 1 else 0 end) as {{ s }}_count
    {%- if not loop.last %},{% endif %}
    {% endfor %}
from {{ ref('stg_orders') }}
group by 1
```

Without the `{% if execute %}` guard, the loop iterates zero times during parsing and the
model compiles to broken SQL.

**`ref()` inside a conditional still creates the dependency.** dbt statically extracts every
`ref` regardless of which branch runs — that is deliberate, and it is why the DAG is reliable.

### Control flow

```sql
{% if target.name == 'prod' %}
    where ordered_at >= '2020-01-01'
{% else %}
    where ordered_at >= dateadd(day, -7, current_date)    -- dev: last week only
{% endif %}

{% set cols = ['revenue', 'cost', 'margin'] %}
{% for c in cols %}
    sum({{ c }}) as total_{{ c }}{% if not loop.last %},{% endif %}
{% endfor %}
```

`loop.first`, `loop.last`, `loop.index` (1-based), `loop.index0` (0-based).

**Dev-only filters are the highest-value Jinja pattern in a project** — they cut dev build
time by an order of magnitude and cost nothing in production.

### Whitespace control

```sql
{%- for c in cols -%}
    {{ c }}{%- if not loop.last -%},{%- endif %}
{%- endfor -%}
```

Missing `-` produces syntactically broken SQL that looks fine in the template. When output is
malformed, read `target/compiled/` — the problem is always visible there.

### Debugging

```sql
{{ log("statuses: " ~ statuses, info=true) }}     -- prints during compilation
{{ print("value: " ~ x) }}                        -- prints during execution
{% do exceptions.raise_compiler_error("bad config: " ~ x) %}
{% do exceptions.warn("deprecated pattern in " ~ model.name) %}
```

`{{ log(..., info=true) }}` is the only way to see what a macro actually returned.

## Macros

```sql
-- macros/cents_to_dollars.sql
{% macro cents_to_dollars(column_name, decimal_places=2) -%}
    round(({{ column_name }} / 100.0)::numeric, {{ decimal_places }})
{%- endmacro %}
```

```sql
select {{ cents_to_dollars('amount_cents') }} as amount_usd
```

**Write a macro when the logic appears three times.** Once, it stays inline — a macro hiding
a single simple expression makes the project harder to read, because every reader now has to
open another file.

### Good macro candidates

- Repeated CASE mappings used across several models.
- Warehouse-specific date or string handling.
- Column-list generation (`dbt_utils.star`).
- Grant and permission statements.
- Schema/database name generation.
- Any transformation with a business rule that must be identical everywhere.

### `adapter.dispatch` — cross-warehouse macros

```sql
{% macro safe_divide(numerator, denominator) -%}
    {{ return(adapter.dispatch('safe_divide', 'my_project')(numerator, denominator)) }}
{%- endmacro %}

{% macro default__safe_divide(numerator, denominator) -%}
    {{ numerator }} / nullif({{ denominator }}, 0)
{%- endmacro %}

{% macro bigquery__safe_divide(numerator, denominator) -%}
    safe_divide({{ numerator }}, {{ denominator }})
{%- endmacro %}
```

dbt picks `<adapter>__safe_divide` if it exists, else `default__safe_divide`. This is how
portable macros work, and it is how you should handle any warehouse-specific SQL rather than
scattering `{% if target.type == '...' %}` through your models.

Override a package's macro by declaring a search order:

```yaml
# dbt_project.yml
dispatch:
  - macro_namespace: dbt_utils
    search_order: ['my_project', 'dbt_utils']    # mine wins if it exists
```

### Custom generic tests

```sql
-- tests/generic/test_positive_or_null.sql
{% test positive_or_null(model, column_name) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null and {{ column_name }} < 0
{% endtest %}
```

```sql
-- with extra arguments
{% test recent_enough(model, column_name, max_age_days=7) %}
select max({{ column_name }}) as most_recent
from {{ model }}
having max({{ column_name }}) < {{ dbt.dateadd('day', -max_age_days, 'current_date') }}
{% endtest %}
```

```yaml
- name: ordered_at
  data_tests:
    - recent_enough:
        max_age_days: 3
```

A generic test returns failing rows. Zero rows = pass.

### `generate_schema_name`

The most commonly overridden macro. dbt's default concatenates
`<target_schema>_<custom_schema>`, which nobody wants in production:

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

Prod gets clean schema names (`marts`, `staging`); dev builds everything into the developer's
personal schema. Sibling macros: `generate_database_name`, `generate_alias_name`.

### Running a macro directly

```bash
dbt run-operation grant_select --args '{"role": "REPORTER"}'
```

```sql
{% macro grant_select(role) %}
    {% set sql %}
        grant usage on schema {{ target.schema }} to role {{ role }};
        grant select on all tables in schema {{ target.schema }} to role {{ role }};
    {% endset %}
    {% do run_query(sql) %}
    {% do log("Granted select to " ~ role, info=true) %}
{% endmacro %}
```

`run_query` returns an Agate table; `{% do %}` executes without rendering output.

## Cross-database macros

Shipped in dbt-core, dispatched per adapter. **Use these instead of writing dialect SQL** —
they are what makes a project portable.

```sql
{{ dbt.dateadd('day', -3, 'ordered_at') }}
{{ dbt.datediff('ordered_at', 'shipped_at', 'day') }}
{{ dbt.date_trunc('month', 'ordered_at') }}
{{ dbt.current_timestamp() }}
{{ dbt.last_day('ordered_at', 'month') }}
{{ dbt.split_part('full_name', "' '", 1) }}
{{ dbt.concat(['first_name', "' '", 'last_name']) }}
{{ dbt.hash('email') }}
{{ dbt.length('order_id') }}
{{ dbt.position("'@'", 'email') }}
{{ dbt.right('order_id', 4) }}
{{ dbt.replace('phone', "'-'", "''") }}
{{ dbt.listagg('product_name', "', '") }}
{{ dbt.safe_cast('amount', api.Column.translate_type('numeric')) }}
{{ dbt.type_string() }} {{ dbt.type_numeric() }} {{ dbt.type_timestamp() }}
{{ dbt.type_int() }} {{ dbt.type_float() }} {{ dbt.type_boolean() }}
{{ dbt.except() }} {{ dbt.intersect() }}
{{ dbt.array_construct(['a','b']) }} {{ dbt.array_append('arr', 'x') }}
```

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
  - package: dbt-labs/dbt_project_evaluator
    version: [">=0.14.0", "<0.15.0"]
  - git: "https://github.com/example/internal-macros.git"
    revision: v2.1.0            # a tag or SHA — never a branch
  - local: ../shared_transforms
```

```bash
dbt deps        # installs to dbt_packages/; must run before anything else in CI
```

Always version-range, and **commit `package-lock.yml`** so CI resolves what you resolved.

### `dbt_utils` — the essential one

**SQL generators**

| Macro | Does |
|---|---|
| `generate_surrogate_key(['a','b'])` | null-safe hash of the grain columns |
| `star(from=ref('m'), except=['x'])` | column list minus exclusions |
| `union_relations([ref('a'), ref('b')])` | union with column reconciliation |
| `date_spine(datepart, start, end)` | a calendar table — the time-spine builder |
| `pivot(column, values)` / `unpivot(...)` | reshape |
| `get_column_values(ref('m'), 'col')` | distinct values, for dynamic pivots |
| `deduplicate(relation, partition_by, order_by)` | dedupe helper |
| `group_by(5)` | `group by 1,2,3,4,5` |
| `haversine_distance(...)` | geo distance |
| `width_bucket(...)` | binning |

**Tests**

`unique_combination_of_columns`, `accepted_range`, `expression_is_true`,
`not_null_proportion`, `at_least_one`, `equality`, `recency`, `cardinality_equality`,
`fewer_rows_than`, `not_accepted_values`, `sequential_values`, `mutually_exclusive_ranges`,
`unique_where` / `not_null_where`, `relationships_where`

### `dbt_expectations`

Great-Expectations-style tests. Best for distributional and format assertions:
`expect_table_row_count_to_be_between`, `expect_column_values_to_match_regex`,
`expect_column_mean_to_be_between`, `expect_column_values_to_be_of_type`,
`expect_column_distinct_count_to_be_between`, `expect_column_values_to_be_increasing`,
`expect_table_row_count_to_equal_other_table`.

### `codegen` — the fastest legitimate shortcut

```bash
dbt run-operation generate_source --args '{"schema_name":"shopify","database_name":"raw"}'
dbt run-operation generate_base_model --args '{"source_name":"shopify","table_name":"orders"}'
dbt run-operation generate_model_yaml --args '{"model_names":["stg_shopify__orders"]}'
```

Generates `sources.yml`, staging SQL, and base `schema.yml` from the warehouse. Treat the
output as a first draft — it gives you every column; you supply grain, descriptions, and
tests.

### `audit_helper` — the migration/refactor tool

```sql
{{ audit_helper.compare_relations(a_relation=..., b_relation=ref('m'), primary_key='id') }}
{{ audit_helper.compare_all_columns(a_relation=..., b_relation=ref('m'), primary_key='id') }}
{{ audit_helper.compare_queries(a_query=..., b_query=...) }}
{{ audit_helper.compare_relation_columns(a_relation=..., b_relation=...) }}
```

`compare_all_columns` gives per-column match rates — it turns "the numbers differ" into
"revenue matches on 99.97% of rows" in one query. Start there.

### `dbt_project_evaluator`

dbt Labs' own best-practice checks, implemented as models that read your manifest. Flags DAG
issues (a mart referencing a source, rejoining of upstream, root models), testing gaps,
documentation gaps, structural violations, and naming problems.

Complementary to `scripts/dbt_project_auditor.py` here: the package runs *in* the warehouse
against a built manifest; the script runs offline in CI from `manifest.json` alone.

### Others worth knowing

| Package | For |
|---|---|
| `elementary` | anomaly detection and test-result history, self-hosted on Core |
| `dbt_artifacts` / `dbt_snowflake_monitoring` | load run artifacts into models for observability |
| `dbt_date` | fiscal calendars and date dimension helpers |
| `metrics` | pre-MetricFlow; do not use in new projects |
| Source packages (`fivetran/shopify_source` etc.) | pre-built staging for common connectors |

Source packages are a real accelerator but they own the staging layer — you inherit their
naming and grain decisions. Read what they build before installing.

## Anti-patterns

- A macro that wraps a single simple expression. Now every reader opens two files.
- Introspective queries without `{% if execute %}`.
- `{% if target.type == 'snowflake' %}` scattered through models instead of
  `adapter.dispatch`.
- Hand-written date arithmetic where a `dbt.` macro exists.
- Unpinned packages, or `revision:` pointing at a branch.
- `package-lock.yml` not committed, so CI resolves different versions.
- Jinja generating SQL so dynamic that nobody can predict the output. If you must run
  `dbt compile` to know what a model does, it is too clever.
- Macros with no docstring and no example.
