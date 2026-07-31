# Migration Playbooks

Legacy SQL into dbt, warehouse swaps, dbt version upgrades, and safe refactors. Every one is
the same problem: **prove the new thing produces the same answer, then cut over with a way
back.**

## The rule

> Never change what a model produces and how it produces it in the same commit.

Refactor first with output held constant and proven identical. Change behavior second, as its
own reviewable diff. Doing both at once means any difference could be either, and you cannot
tell which.

## Proving equivalence with `audit_helper`

```yaml
packages:
  - package: dbt-labs/audit_helper
    version: [">=0.12.0", "<0.13.0"]
```

```sql
-- analyses/audit_fct_orders.sql
{{ audit_helper.compare_relations(
     a_relation=api.Relation.create(database='LEGACY', schema='reporting', identifier='orders_summary'),
     b_relation=ref('fct_orders'),
     primary_key='order_id',
     exclude_columns=['dbt_updated_at', '_loaded_at']
) }}
```

```bash
dbt compile --select audit_fct_orders
# run target/compiled/.../audit_fct_orders.sql in the warehouse
```

Returns a reconciliation: rows in both and identical, in both but different, in A only, in B
only.

**Start with `compare_all_columns`**, not `compare_relations` — it gives per-column match
rates, turning "the numbers are different" into "revenue matches on 99.97% of rows" in one
query:

```sql
{{ audit_helper.compare_all_columns(a_relation=..., b_relation=ref('fct_orders'),
                                    primary_key='order_id') }}
```

Also available: `compare_column_values`, `compare_queries` (two SELECTs, nothing
materialized), `compare_relation_columns` (schema-only diff).

## Playbook 1 — Legacy SQL / stored procedures into dbt

### Step 1: inventory (do not skip)

| Field | Why |
|---|---|
| Output table and grain | what you are reproducing |
| **Consumers in the last 90 days** | query history. **30–50% typically have none** |
| Inputs | raw tables and other procedure outputs |
| Run cadence and duration | sets the materialization |
| Procedural constructs | cursors, temp tables, loops, `IF` — rethink, do not translate |
| Side effects | writes elsewhere, emails, API calls — dbt cannot do these |

Finding the dead scripts first is the single biggest time saver in the whole project. Query
your warehouse's access history for reads against each output table.

### Step 2: translate patterns, not lines

| Legacy | dbt |
|---|---|
| Temp table | a CTE, or an intermediate model if reused |
| Cursor / row loop | a set-based query. If genuinely iterative, it does not belong in dbt |
| `IF EXISTS DROP CREATE` | the materialization handles it |
| `MERGE` | `materialized='incremental'`, `incremental_strategy='merge'` |
| `TRUNCATE` + `INSERT` | `materialized='table'` |
| Hardcoded dates | `{{ var('start_date') }}` or `current_date` |
| Hardcoded table names | `{{ source() }}` / `{{ ref() }}` — non-negotiable |
| Procedure calling procedures | the dbt DAG. Delete the orchestration code |
| Repeated CASE mapping | a macro, or a seed if it is a lookup table |
| `EXEC` / dynamic SQL | Jinja, if the shape is bounded. Otherwise redesign |
| Error handling / retries | the orchestrator's job |
| Logging table writes | dbt artifacts, or a post-hook |

Do not port procedural structure into SQL. A 600-line procedure with three cursors becomes
four set-based models — and becomes readable in the process.

### Step 3: migrate in vertical slices

Pick **one output table with a real consumer** and build its whole slice: sources → staging →
intermediate → mart. Prove it. Cut it over. Then the next.

Building every staging model first means months before anything is provably correct or usable.

### Step 4: strangler cutover

```
Phase 1  legacy writes reporting.orders_summary   ← all consumers read this
         dbt writes  analytics.fct_orders         ← nobody reads it yet
         a daily audit_helper comparison runs and must be clean

Phase 2  the audit has been clean for 2 weeks
         reporting.orders_summary becomes a VIEW over analytics.fct_orders
         consumers unchanged and unaware

Phase 3  consumers repointed to analytics.fct_orders one at a time
         the legacy job is DISABLED but not deleted

Phase 4  after one full business cycle (a month-end close, a quarterly report),
         the legacy job and its tables are deleted
```

The compatibility view in Phase 2 is what makes this safe: cutover is one line and rollback is
the same one line. Do not skip it.

**Do not delete the legacy system until a full business cycle has passed.** Month-end and
quarter-end logic is where the differences you did not find are hiding.

### Common differences you will find

| Difference | Usual cause |
|---|---|
| Row counts differ by a handful | soft-deleted or test rows the legacy job filtered implicitly |
| Amounts differ in the last decimal | rounding order, or a different numeric precision |
| One day is always wrong | timezone — the legacy job ran in local time |
| Month-end differs | fiscal calendar logic buried in the procedure |
| Historic rows differ, recent ones match | the legacy job never backfilled a past bug fix |
| Everything differs by a constant factor | a fan-out in one of the two |

Each of these is a real finding. Document it and decide deliberately which behavior is
correct — often the legacy one is the bug, and fixing it is a business conversation, not an
engineering one.

## Playbook 2 — Cross-platform warehouse migration

dbt makes this far easier than a raw SQL migration, but dialect differences are real.

### Order

1. Install the new adapter, add a target, `dbt debug`.
2. `dbt parse` — confirms the project is intact.
3. `dbt compile --target new` — the first real signal.
4. `dbt build --select staging --target new` — most dialect issues surface here, in the casts.
5. Build layer by layer, fixing as you go.
6. `audit_helper` between the two platforms for every mart.
7. Strangler cutover.

### Use cross-database macros, do not hand-fix

```sql
{{ dbt.dateadd('day', -3, 'ordered_at') }}
{{ dbt.datediff('ordered_at', 'shipped_at', 'day') }}
{{ dbt.date_trunc('month', 'ordered_at') }}
{{ dbt.current_timestamp() }}
{{ dbt.safe_cast('amount', api.Column.translate_type('numeric')) }}
{{ dbt.split_part('full_name', "' '", 1) }}
{{ dbt.concat(['a', "' '", 'b']) }}
{{ dbt.listagg('product_name', "', '") }}
{{ dbt.hash('email') }}
{{ dbt.type_string() }} {{ dbt.type_numeric() }} {{ dbt.type_timestamp() }}
{{ dbt.except() }} {{ dbt.intersect() }}
```

For anything not covered, use `adapter.dispatch` rather than scattering
`{% if target.type == '...' %}` through models:

```sql
{% macro safe_divide(n, d) -%}
    {{ return(adapter.dispatch('safe_divide', 'my_project')(n, d)) }}
{%- endmacro %}
{% macro default__safe_divide(n, d) -%} {{ n }} / nullif({{ d }}, 0) {%- endmacro %}
{% macro bigquery__safe_divide(n, d) -%} safe_divide({{ n }}, {{ d }}) {%- endmacro %}
```

### The high-friction differences

| Area | Watch for |
|---|---|
| `qualify` | not supported on Postgres/Redshift — rewrite as a subquery. The most common single failure |
| Identifier case | Snowflake uppercases, Databricks lowercases, BigQuery is case-sensitive |
| Safe cast | `try_cast` / `safe_cast` / neither |
| Numeric precision | defaults differ; contracts and unit tests both trip on it |
| Semi-structured | `variant` vs `STRUCT` vs `jsonb` — usually needs a genuine rewrite |
| Window frames | default frame differs on some engines |
| Null ordering | `nulls first` / `nulls last` defaults differ, which changes dedup results |

### Also migrate

- **Materialization configs** — `cluster_by`, `partition_by`, `dist`/`sort`, `file_format` are
  adapter-specific and will error or silently no-op.
- **Incremental strategies** — `insert_overwrite` is BigQuery/Spark; `delete+insert` is
  Postgres/Redshift. Check every incremental model.
- **Seeds** — `column_types` differ. Never let dbt infer them.
- **Unit tests** — fixture type literals are the most platform-sensitive thing in the project.
  Expect to convert several to `format: sql` with explicit casts.
- **Grants** — syntax and role names differ entirely.
- **Snapshots** — plan these **first**. They hold history you cannot regenerate; you must copy
  the tables across, not rebuild them.

## Playbook 3 — Upgrading dbt Core

```bash
pip install --upgrade dbt-core dbt-snowflake
dbt parse                                              # deprecation warnings appear here
dbt build --select state:modified+ --defer --state prod/ --warn-error
```

1. **Read the migration guide for every intervening minor version.** They are cumulative and
   each has its own breaking changes.
2. **One minor version at a time.** 1.5 → 1.9 in one jump makes every failure ambiguous.
3. **`--warn-error`** turns deprecation warnings into failures — exactly what you want during
   an upgrade.
4. **Upgrade packages together.** `dbt_utils`, `dbt_expectations`, and `codegen` all have
   dbt-version floors; a mismatch produces errors that look like your bug.
5. **Regenerate the production manifest afterwards.** `state:modified` against a manifest from
   a different dbt version matches everything, silently breaking slim CI.

Version-gated features to know when reading older projects:

| Feature | Since |
|---|---|
| `unit_tests:` | 1.8 |
| `data_tests:` (renamed from `tests:`) | 1.8 |
| Model contracts + versions | 1.5 |
| Groups + `access:` | 1.5 |
| `microbatch` incremental strategy | 1.9 |
| Snapshots in YAML | 1.9 |
| `dbt_valid_to_current` | 1.9 |
| `saved_queries` / exports | 1.7+ |
| `time_spine:` model config | 1.9 |
| `--empty` | 1.7 |
| `dbt retry` | 1.6 |

## Playbook 4 — Refactoring a model with consumers

1. **Blast radius.**
   ```bash
   python scripts/model_dependency_analyzer.py --manifest target/manifest.json \
       --model fct_orders --direction down --depth 99
   ```
2. **Check governance.** Contracted or versioned? The change is governed.
3. **Snapshot current output:**
   ```sql
   create table audit.fct_orders_before as select * from analytics.fct_orders;
   ```
4. **Write a unit test capturing current behavior** — the refactor then proves equivalence
   rather than asserting it.
5. **Change one thing at a time**, `dbt build --select <model>+` between each.
6. **Prove equivalence** with `compare_all_columns` against the audit table.
7. **Then** make the behavior change, as a separate commit.

## Checklists

### Legacy migration

- [ ] Inventory complete; scripts with no live consumer marked for retirement, not migration
- [ ] Every target table has a named consumer
- [ ] Slices ordered by consumer value, not DAG layer
- [ ] `audit_helper` comparison written for every mart and running on a schedule
- [ ] Compatibility views in place — cutover and rollback are both one line
- [ ] Differences documented and deliberately resolved, not averaged away
- [ ] Legacy disabled, not deleted, for at least one full business cycle
- [ ] A month-end close has run through the new system before deletion
- [ ] Consumers notified with dates

### Platform migration

- [ ] New adapter installed; `dbt debug` passes
- [ ] Dialect SQL replaced with `dbt.` macros, not hand-fixed per model
- [ ] Materialization configs reviewed per model
- [ ] Incremental strategies checked for adapter support
- [ ] Seed `column_types` set explicitly
- [ ] Unit test fixtures converted where types are strict
- [ ] Snapshots copied, not rebuilt
- [ ] `audit_helper` clean on every mart across platforms
- [ ] Grants recreated

### dbt upgrade

- [ ] Migration guides read for every intervening minor version
- [ ] One minor version at a time
- [ ] Packages upgraded together
- [ ] `--warn-error` run clean
- [ ] Production manifest regenerated
- [ ] CI verified to still select the right nodes

## Anti-patterns

- Translating a stored procedure line by line into one enormous model.
- Migrating every table because it exists, without checking who reads it.
- Building all staging first, so nothing is provably correct for months.
- Refactoring and changing behavior in the same commit.
- "It looks right" instead of an `audit_helper` comparison.
- Deleting the legacy system the day after cutover, before month-end.
- Hand-fixing dialect differences model by model.
- Upgrading four dbt minor versions in one jump.
- Forgetting to regenerate the production manifest after an upgrade, silently breaking slim CI.
- Averaging away a difference instead of finding out which system is right.
