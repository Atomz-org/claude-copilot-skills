---
name: migration-and-refactoring
description: Move work into or across dbt Core safely — legacy SQL scripts and stored procedures into dbt models, migrating a dbt project between warehouse platforms (Snowflake/BigQuery/Databricks/Redshift/Postgres), upgrading dbt Core versions, and refactoring existing models without changing their output. Covers equivalence proving with audit_helper, the strangler pattern, SQL dialect translation, and cutover planning. Use when converting legacy SQL to dbt, when changing warehouses, when upgrading dbt, or when refactoring a model that has consumers.
---

# Migration and Refactoring

Every migration is the same problem: **prove the new thing produces the same answer as the
old thing**, then cut over with a way back.

## The rule that governs all of it

> Never change what a model produces and how it produces it in the same commit.

Refactor first, with output held constant and proven identical. Change behavior second, as
its own reviewable diff. Doing both at once means any difference could be either the
refactor or the intended change, and you cannot tell which.

## Proving equivalence

The one tool that makes migration tractable is `audit_helper`.

```yaml
# packages.yml
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
     exclude_columns=['dbt_updated_at']
) }}
```

```bash
dbt compile --select audit_fct_orders
# run target/compiled/.../audit_fct_orders.sql in the warehouse
```

Output is a row-count reconciliation: rows in both and identical, in both but different, in
A only, in B only.

When rows differ, localize the column:

```sql
{{ audit_helper.compare_all_columns(
     a_relation=..., b_relation=ref('fct_orders'), primary_key='order_id'
) }}
```

This gives a per-column match rate, which turns "the numbers are different" into "revenue
matches on 99.97% of rows" in one query. Start there, always.

Also useful: `compare_column_values`, `compare_queries` (compare two SELECTs without
materializing), and `compare_relation_columns` (schema-only diff — types and names).

## Legacy SQL and stored procedures into dbt

### 1. Inventory before converting

For each script or procedure:

| Field | Why |
|---|---|
| What it produces | the target table, and its grain |
| Who consumes it | if nobody, do not migrate it — retire it |
| Inputs | which raw tables, which other procedure outputs |
| Run cadence and duration | sets the materialization |
| Procedural constructs | cursors, temp tables, loops, `IF`, `MERGE` — these need rethinking, not translating |
| Side effects | writes to other tables, emails, API calls — dbt cannot do these |

**Typically 30–50% of a legacy warehouse's scripts have no live consumer.** Finding that out
first is the single biggest time saver in the project. Check query history for reads against
each output table over the last 90 days.

### 2. Translate the patterns, not the lines

| Legacy construct | dbt equivalent |
|---|---|
| Temp table | a CTE, or an intermediate model if reused |
| Cursor / row-by-row loop | a set-based query. If genuinely iterative, it does not belong in dbt |
| `IF EXISTS ... DROP ... CREATE` | dbt's materialization handles this |
| `MERGE` statement | `materialized='incremental'` with `incremental_strategy='merge'` |
| `TRUNCATE` + `INSERT` | `materialized='table'` |
| Hardcoded date literals | `{{ var('start_date') }}` or `current_date` |
| Hardcoded table names | `{{ source() }}` and `{{ ref() }}` — non-negotiable |
| A procedure calling other procedures | the dbt DAG. Delete the orchestration code |
| Repeated CASE mapping | a macro, or a seed file if it is a lookup table |
| `EXEC` / dynamic SQL | Jinja, if the shape is bounded. Otherwise redesign |
| Error handling / retry logic | the orchestrator's job, not the model's |

Do not port procedural structure into SQL. A 600-line procedure with three cursors becomes
four set-based models, and it becomes readable in the process.

### 3. Migrate in slices, not layers

Pick one **output table with a real consumer**, and build its whole vertical slice: sources →
staging → intermediate → mart. Prove it matches. Cut it over. Then the next one.

The alternative — building every staging model first — means months before anything is
provably correct or usable.

### 4. Strangler cutover

Run both systems in parallel and shift consumers one at a time.

```
Phase 1  legacy writes reporting.orders_summary  ← every consumer reads this
         dbt writes  analytics.fct_orders        ← nobody reads it yet
         a daily audit_helper comparison runs and must be clean

Phase 2  legacy still writes; the audit has been clean for 2 weeks
         a view reporting.orders_summary now selects from analytics.fct_orders
         consumers are unchanged and unaware

Phase 3  consumers repointed to analytics.fct_orders one at a time
         the legacy job is disabled but NOT deleted

Phase 4  after one full business cycle (a month-end close, a quarterly report),
         the legacy job and its tables are deleted
```

The compatibility view in Phase 2 is what makes this safe: the cutover is a one-line change
and the rollback is the same one line. Do not skip it.

**Do not delete the legacy system until a full business cycle has passed.** Month-end and
quarter-end logic is where the differences you did not find are hiding.

## Cross-platform migration

Moving a dbt project between warehouses. dbt makes this far easier than a raw SQL migration,
but the SQL dialect differences are real.

### Order of work

1. **Install the new adapter**, add a new target to `profiles.yml`, `dbt debug` against it.
2. **`dbt parse`** — catches nothing dialect-specific, but confirms the project is intact.
3. **`dbt compile --target new`** — first real signal.
4. **Build staging only** — `dbt build --select staging --target new`. Most dialect issues
   surface here, in the casts.
5. **Build layer by layer**, fixing as you go.
6. **`audit_helper` between the two platforms** for every mart.
7. **Cut over** with the strangler pattern.

### Dialect differences that bite

| Area | Snowflake | BigQuery | Databricks | Postgres/Redshift |
|---|---|---|---|---|
| Date add | `dateadd(day, 1, d)` | `date_add(d, interval 1 day)` | `date_add(d, 1)` | `d + interval '1 day'` |
| Date diff | `datediff(day, a, b)` | `date_diff(b, a, day)` | `datediff(b, a)` | `b - a` |
| String concat | `\|\|` or `concat()` | `concat()` | `\|\|` | `\|\|` |
| Safe cast | `try_cast` | `safe_cast` | `try_cast` | none — use a `case` |
| Current time | `current_timestamp()` | `current_timestamp()` | `current_timestamp()` | `now()` |
| Identifier case | uppercases unquoted | case-sensitive | lowercases | lowercases |
| Booleans | native | native | native | native (Redshift is quirky) |
| Semi-structured | `variant`, `:` path | `STRUCT`/`ARRAY`, dot | `MAP`/`STRUCT` | `jsonb` |
| Regex | `regexp_like` | `regexp_contains` | `rlike` | `~` |
| `qualify` | yes | yes | yes | **no** — use a subquery |

**Use cross-database macros instead of hand-fixing.** dbt ships adapter-dispatching versions
of the common ones, and this is the whole point:

```sql
{{ dbt.dateadd('day', -3, 'ordered_at') }}
{{ dbt.datediff('ordered_at', 'shipped_at', 'day') }}
{{ dbt.current_timestamp() }}
{{ dbt.safe_cast('amount', api.Column.translate_type('numeric')) }}
{{ dbt.split_part('full_name', "' '", 1) }}
{{ dbt.concat(['first_name', "' '", 'last_name']) }}
{{ dbt.type_string() }} {{ dbt.type_numeric() }} {{ dbt.type_timestamp() }}
{{ dbt.hash('email') }}
{{ dbt.listagg('product_name', "', '") }}
{{ dbt_utils.star(from=ref('stg_orders'), except=['_loaded_at']) }}
```

Anywhere you cannot avoid platform-specific SQL, use `adapter.dispatch` (see
[references/jinja_and_macros.md](../../../references/jinja_and_macros.md)) rather than a
`{% if target.type == 'snowflake' %}` scattered through models.

### Also migrate

- **Materialization configs** — `cluster_by`, `partition_by`, `dist`/`sort`, `file_format`
  are all adapter-specific and will error or silently no-op on the new platform.
- **Incremental strategies** — `insert_overwrite` is BigQuery/Spark; `delete+insert` is
  Postgres/Redshift. Check each incremental model.
- **Seeds** — `column_types` differ. Never let dbt infer them.
- **Unit tests** — type literals in fixtures are the most platform-sensitive thing in the
  project. Expect to convert several to `format: sql` with explicit casts.
- **Grants** — `grants:` config syntax and role names differ entirely.
- **Snapshots** — plan these first. They hold history you cannot regenerate; you must copy
  the tables across, not rebuild them.

## Upgrading dbt Core

```bash
pip install --upgrade dbt-core dbt-snowflake
dbt parse                                     # deprecation warnings appear here
dbt build --select state:modified+ --defer --state prod/ --warn-error
```

1. **Read the migration guide** for every intervening minor version — they are cumulative
   and each has its own breaking changes.
2. **Upgrade one minor version at a time.** 1.5 → 1.9 in one jump makes every failure
   ambiguous.
3. **`--warn-error`** turns deprecation warnings into failures, which is exactly what you
   want during an upgrade.
4. **Upgrade packages together.** `dbt_utils`, `dbt_expectations`, and `codegen` all have
   dbt-version floors, and a version mismatch produces errors that look like your bug.
5. **Regenerate the production manifest** after upgrading. `state:modified` against a
   manifest from a different dbt version matches everything, silently breaking slim CI.

Version-gated features to know about when reading older projects: `unit_tests:` (1.8+),
`microbatch` (2.0), snapshots in YAML (2.0), `dbt_valid_to_current` (2.0), `saved_queries`
and `time_spine:` config (1.7–1.9 depending on the feature).

## Refactoring an existing model

1. **Blast radius.**
   ```bash
   python scripts/model_dependency_analyzer.py --manifest target/manifest.json \
       --model fct_orders --direction down --depth 99
   ```
2. **Check governance.** Contracted or versioned? The change is governed — route through
   `dbt-mesh-governance`.
3. **Snapshot the current output** into an audit schema:
   ```sql
   create table audit.fct_orders_before as select * from analytics.fct_orders;
   ```
4. **Write a unit test capturing current behavior** before changing anything, so the refactor
   proves equivalence rather than asserting it.
5. **Change one thing at a time**, `dbt build --select <model>+` between each.
6. **Prove equivalence** with `compare_all_columns` against the audit table.
7. **Then** make the behavior change, as a separate commit with its own diff.

## Migration checklist

- [ ] Inventory complete; scripts with no live consumer are marked for retirement, not migration
- [ ] Every target table has a named consumer
- [ ] Slices ordered by consumer value, not by DAG layer
- [ ] `audit_helper` comparison written for every mart, and running on a schedule
- [ ] Compatibility views in place so cutover and rollback are both one line
- [ ] Cross-database macros used instead of hand-fixed dialect SQL
- [ ] Snapshots planned first — the history cannot be regenerated
- [ ] Legacy system disabled, not deleted, for at least one full business cycle
- [ ] A month-end close has run through the new system before deletion
- [ ] Consumers notified with dates, not just "we're migrating"

## Anti-patterns

- Translating a stored procedure line by line into one enormous model.
- Migrating every table because it exists, without checking whether anything reads it.
- Building all staging models first, so nothing is provably correct for months.
- Refactoring and changing behavior in the same commit.
- "It looks right" instead of an `audit_helper` comparison.
- Deleting the legacy system the day after cutover, before month-end has run.
- Hand-fixing dialect differences model by model instead of using `dbt.` macros.
- Upgrading four dbt minor versions in one jump.
- Forgetting to regenerate the production manifest after a dbt upgrade, silently breaking
  slim CI.

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| "convert this stored procedure to dbt" | An inventory and a slice plan — not one enormous model translated line by line |
| "refactor fct_orders" | Equivalence proved with `audit_helper`, behavior unchanged, in its own commit |
| "we're moving from Redshift to Snowflake" | The dialect differences that actually bite, and a cutover plan with a rollback |
| "upgrade dbt Core" | One minor version at a time, and the production manifest regenerated afterwards |

**Worked example**

> "refactor fct_orders — it's a 400-line model"

```sql
-- analyses/audit_fct_orders.sql — written BEFORE the refactor
{{ audit_helper.compare_all_columns(
     a_relation=api.Relation.create(schema='audit', identifier='fct_orders_before'),
     b_relation=ref('fct_orders'),
     primary_key='order_id'
) }}
```

```bash
# 1. Snapshot the current output as the baseline
create table analytics.audit.fct_orders_before as select * from analytics.marts.fct_orders;

# 2. Refactor — structure only, no behavior change in this commit
#    400 lines → int_order_lines_by_order, int_refunds_by_order, fct_orders

# 3. Prove equivalence, per column
dbt build --select fct_orders
dbt compile --select audit_fct_orders
# run target/compiled/.../audit_fct_orders.sql in the warehouse
```

```
column           match_rate
order_id            100.0%
total_amount        100.0%
refund_amount        99.7%   ← not equivalent. 312 orders differ.
                              The old model used an inner join and dropped unrefunded
                              orders' zero rows. Which behavior is correct is a business
                              question — answer it before merging, in its own commit.
```

`compare_all_columns` localizes the difference to one column in seconds; a row-level diff
would have shown 312 mismatched rows and no cause. And "it looks right" would have shipped
a 0.3% revenue change nobody chose.

Reference: [references/migration_playbooks.md](../../../references/migration_playbooks.md).
