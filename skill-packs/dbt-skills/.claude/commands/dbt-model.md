---
description: Design and scaffold a dbt model end to end — blueprint, SQL, schema.yml, tests
argument-hint: <the business concept, or an existing model to refactor>
---

Build this model: **$ARGUMENTS**

---

## Precondition

A use-case spec with a decision, a named consumer, and a **stated grain**. If there is
none, run `/new-use-case` first — do not skip it because the request sounds well specified.
The gap is almost always the grain or the consumer.

**If this model is a fact, dimension, or bridge**, it must also trace to a row in a data
model canvas. Check `use-cases/<slug>/data-model-canvas.md`:

| Situation | Do |
|---|---|
| The row exists in the grain matrix | Copy its grain, PK, and SCD type into the blueprint verbatim. Do not restate them differently — a grain that differs between canvas and blueprint means one of them is wrong. |
| No canvas, and this is the only model | Proceed. Record the grain in the blueprint; note that no canvas was needed. |
| No canvas, but the subject area needs several models or a shared dimension | Stop and run `/data-model <subject area>` first. |
| The canvas has a row, but you disagree with its grain | Change the canvas first, then build. The canvas is the decision record; silently building something else is how the two diverge. |

## 1. Read the project

```bash
cat dbt_project.yml
dbt ls --resource-type model --output name | head -50
dbt ls --resource-type source --output name
```

Match the project's existing layer conventions, naming, and macros. **Consistency with the
project beats consistency with any style guide.** Reuse an existing staging model rather
than building a second one for the same source table.

## 2. Blueprint before SQL

Load the `dbt-model-design` skill. Fill
[templates/model-blueprint.md](../../templates/model-blueprint.md) into
`use-cases/<slug>/model-blueprint.md`. Every row must be filled before you write SQL —
especially:

- **Data model row** — which canvas entry this implements, and the model's kind (fact
  type / dimension / bridge). Blank here means the dimensional decisions have not been
  made, only deferred.
- **Grain**, one sentence, plus the PK that enforces it — **copied from the canvas**, not
  re-derived.
- **Join plan** — every input's expected cardinality (1:1 / 1:N / N:1) and, for each 1:N,
  how the grain is preserved. This is the single most common source of "the totals are
  wrong".
- **Materialization**, with a one-line reason. View by default; incremental only when a
  **measured** full refresh is too slow.

## 3. Build layer by layer

Sources → staging → intermediate → marts, running as you go:

```bash
dbt build --select stg_<source>__<entity>
dbt build --select int_<entity>_<verbed>
dbt build --select fct_<entity>
```

**Never write three layers then run once.** Each layer's failure is cheap to diagnose in
isolation and expensive to diagnose together.

Patterns to copy: [templates/dbt-patterns.md](../../templates/dbt-patterns.md).

## 4. Tests and docs

Load `testing-and-documentation`. Scaffold, then fill in the semantics by hand:

```bash
dbt docs generate
python scripts/schema_yml_generator.py --manifest target/manifest.json \
    --model <model> --catalog target/catalog.json --infer-tests
```

Minimum bar: `unique` + `not_null` on the PK, `relationships` on every FK,
`accepted_values` on every closed domain, and a description stating the grain.

**If the model contains a CASE, a window function, regex, date math, or a fan-out-resolving
join, it needs a unit test.** Load `dbt-unit-testing`:

```bash
python scripts/unit_test_generator.py --manifest target/manifest.json \
    --model <model> --catalog target/catalog.json --adapter <adapter>
```

The generator supplies structure. **Write the expected output by hand** — deriving it with
the model's own expression proves only that the expression equals itself.

## 5. If incremental

Load `incremental-and-snapshots`. Non-negotiable:

- `unique_key` set for `merge` / `delete+insert`;
- lookback sized from **measured** p99 arrival lag, with the measurement cited in a comment;
- the filter anchored to `max()` in `{{ this }}`, **never `current_date`**;
- `on_schema_change` set explicitly;
- `--full-refresh` verified to reproduce the incremental result.

## 6. Verify and check impact

```bash
dbt build --select <model>+
python scripts/dbt_project_auditor.py --manifest target/manifest.json --strict
python scripts/model_dependency_analyzer.py --manifest target/manifest.json \
    --model <model> --direction down
python scripts/contract_breaking_change_detector.py \
    --base prod/manifest.json --head target/manifest.json --strict
```

If refactoring an existing model, prove equivalence rather than asserting it:

```sql
-- analyses/audit_<model>.sql
{{ audit_helper.compare_all_columns(
     a_relation=api.Relation.create(schema='audit', identifier='<model>_before'),
     b_relation=ref('<model>'), primary_key='<pk>') }}
```

---

## Rules that bind here

[Rules 4, 18–27](../rules/analytics-engineering-rules.md): declare the grain first; one
concept one model; layer discipline; a tested primary key on every model; materialization
is a decision with a reason; incremental models must be idempotent; `select *` does not
survive into a mart.

## Output

The model files themselves, plus a summary of:

- the grain sentence and the PK;
- the join plan with cardinalities;
- the materialization decision and its reason;
- the tests added, and which models still need a unit test;
- downstream impact and any breaking change;
- the build command and the rollback path;
- anything marked `[NEEDS INPUT]`.
