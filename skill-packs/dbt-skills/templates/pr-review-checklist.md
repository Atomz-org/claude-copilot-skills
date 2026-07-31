# dbt PR Review Checklist

Separate **blocking** from **nice to have** in your review. A review that lists fifteen
undifferentiated comments gets skimmed and ignored.

Every finding needs: the file, what would break in production, and the fix. A finding you
cannot state a failure mode for is a preference — label it as one, or drop it.

---

## Automated gates (run these first — seconds, no warehouse)

```bash
dbt deps && dbt parse
python scripts/dbt_project_auditor.py --manifest target/manifest.json --strict
python scripts/contract_breaking_change_detector.py --base prod/manifest.json --head target/manifest.json --strict
python scripts/test_coverage_reporter.py --manifest target/manifest.json --layer marts --min-coverage 0.9 --strict
python scripts/semantic_layer_validator.py --path models/ --strict
python scripts/dimensional_model_validator.py --manifest target/manifest.json --strict
dbt build --select state:modified+ --defer --state prod/ --empty     # zero data scanned
dbt build --select state:modified+ --defer --state prod/ --warn-error
```

- [ ] All six gates pass
- [ ] `dbt build --select state:modified+` is green

---

## Blocking

### Grain and correctness
- [ ] Every new model states its grain in one sentence in its description
- [ ] Every model has a primary key tested with `unique` + `not_null` (or a composite grain test)
- [ ] Every join's expected cardinality is stated, and 1:N joins are aggregated before joining
- [ ] No `sum()` across a fanned-out join
- [ ] No `distinct` used to paper over a fan-out
- [ ] Dedup with `row_number()` has a fully deterministic `order by`

### References
- [ ] `source()` and `ref()` only — no hardcoded `database.schema.table`
- [ ] Marts do not reference sources directly
- [ ] Marts do not reference another mart's internals
- [ ] Staging models do not join or aggregate

### Tests
- [ ] Every assumption in the use-case spec has a corresponding test
- [ ] Every model containing CASE, a window function, regex, date math, or a fan-out-resolving join has a **unit test**
- [ ] `relationships` on nullable FKs is scoped with `where: <col> is not null`
- [ ] No test was deleted; any narrowing uses `where:` with a recorded reason
- [ ] No test sits at `severity: warn` as a way to merge a failure

### Incremental
- [ ] `unique_key` set for `merge` / `delete+insert`
- [ ] Lookback window sized from **measured** arrival lag, with the measurement cited
- [ ] Filter anchored to `max()` in `{{ this }}`, not `current_date`
- [ ] `on_schema_change` set explicitly (not left at `ignore`)
- [ ] `--full-refresh` reproduces the incremental result — stated how this was verified
- [ ] Full-refresh cost and duration stated in the PR description

### Governance
- [ ] Breaking-change detector clean, or every break is versioned with a `deprecation_date`
- [ ] Contracted models: `data_type` on every column, matching what the warehouse produces
- [ ] `access: public` models have an enforced contract
- [ ] **Grain changes flagged explicitly** — they pass every automated check and silently break every downstream number

### Sources
- [ ] New sources have `loaded_at_field` and `freshness:` (or an explicit `freshness: null`)
- [ ] `loaded_at_field` is a warehouse load timestamp, not a source-system `updated_at`
- [ ] Source primary keys tested at the source level

### Delivery
- [ ] Rollback path stated in the PR description
- [ ] New marts have an `exposures:` entry or a downstream model
- [ ] Owner group set, and its email/channel resolves to a real destination
- [ ] Downstream consumers of any changed model have been notified

---

## Nice to have

- [ ] Descriptions say more than the model name; every mart column documented
- [ ] Shared definitions in `docs` blocks rather than duplicated
- [ ] Import CTEs at the top, one `select * from final` at the bottom
- [ ] CTEs named for their contents
- [ ] Columns enumerated in mart projections, not `select *`
- [ ] Comments explain *why*, not *what*
- [ ] Naming matches the project's convention
- [ ] Model under ~150 lines; over 300 suggests splitting
- [ ] Expensive tests tagged `nightly` rather than running on every CI build
- [ ] Dev-only filter (`{% if target.name != 'prod' %}`) on large models

---

## Dimensional shape

Only when the PR touches a fact, a dimension, or a bridge.

- [ ] The fact covers exactly one business process, and its grain is one sentence in the
      description.
- [ ] Every measure is true at that grain — no measure that belongs to a coarser entity.
- [ ] Additivity is stated per measure; no ratio or average is stored as a fact column.
- [ ] Every foreign key has a `relationships` test **and** either `not_null` or a
      documented unknown member. A null FK silently drops rows from consumers' inner joins.
- [ ] A dimension used by a second business process is conformed, not copied — same key,
      same table, shared domain.
- [ ] Degenerate dimensions stayed on the fact rather than becoming one-column tables.
- [ ] Bridge tables carry an allocation factor if totals must reconcile.
- [ ] Any denormalized attribute on a fact has an explicit as-was vs as-is decision.

---

## Snapshots — read carefully, these are unrecoverable

- [ ] Snapshots the **raw source**, not a transformed model
- [ ] `unique_key` and `strategy` unchanged from the first run
- [ ] Target schema is shared and not environment-suffixed
- [ ] A backup exists before any structural change
- [ ] `strategy: timestamp` verified — does `updated_at` actually move on every change?

An incremental bug is recoverable with a full refresh. A snapshot that missed six months
of changes is not recoverable at all.

---

## Performance

- [ ] `run_results_analyzer.py --compare` shows no unexplained regression
- [ ] Large model has an appropriate cluster/partition/sort key
- [ ] Filters pushed into staging, not applied after a full scan in the mart
- [ ] No expensive full-table reconciliation test added to the CI path

---

## Verdict

Give one, with reasons:

- **Merge** — the bar is met. Say so without hedging and without inventing nitpicks.
- **Merge after** — a short list of blocking gaps. Each names the file, the missing test,
  and the failure it would let through.
- **Do not merge** — the change is unsafe. State the specific breakage, not a general worry.
