# Analytics Engineering Rules

Binding rules for all dbt Core work in this repository. When a rule conflicts with a
request, raise the conflict once, then follow the user's decision.

These rules assume **dbt Core** — the open-source CLI. There is no Cloud scheduler, no
Cloud-hosted Semantic Layer API, no Discovery API, and no managed CI. Every capability
below is reachable from `dbt` on a machine you control, plus the JSON artifacts in
`target/`.

## Framing

1. **No model before a use-case spec.** Every engagement starts by writing
    `skill-packs/dbt-skills/use-cases/<slug>/use-case-spec.md`. A request that sounds well specified usually
   still has an undefined grain or an unnamed consumer.
2. **Name the decision.** If no action changes based on the output, it is a reporting
   request — answer it with a query and say so. Do not add a mart to the DAG for a
   question asked once.
3. **Name the consumer before the model.** A mart with no exposure, dashboard, or
   downstream model is speculative work. Declare it in `exposures:` or do not build it.
4. **Declare the grain in one sentence** — "one row per `<entity>` per `<period>`" —
   before writing any SQL. Every ambiguity downstream traces back to a grain nobody wrote
   down.
5. **Never invent a number or a name.** Unknown table names, row counts, freshness SLAs,
   and business definitions are marked `[NEEDS INPUT]` and the design continues around
   them.

## Data modeling

6. **The conceptual model precedes the physical one.** For any subject area producing
   more than one model, write the entities, relationships, and keys into a data model
   canvas before the first blueprint. A single model on a single source may skip this.
7. **One entity, one definition, one table.** A dimension used by two business processes
   must be conformed — same key, same definition, one model, in a shared domain. Two
   `dim_customer` tables with different keys means the two stars can never be compared,
   and nothing in dbt will ever tell you.
8. **Cardinality and optionality are both explicit.** Every relationship states 1:1, 1:N,
   or N:M *and* which side is optional. The optionality decides `inner` versus `left`,
   and an optional foreign key needs an unknown member row rather than a null.
9. **Keys are never hashed from mutable attributes.** A surrogate key hashes exactly the
   columns that define the grain. Include anything that can change and the key changes
   with it, breaking every downstream join while both sides stay internally consistent.
10. **Every table declares its grain before its columns**, and every measure is checked
    against that grain. A measure true at a coarser grain is double-counted, passes every
    test, and produces a dashboard that looks correct.
11. **Additivity is recorded per measure.** Additive, semi-additive, or non-additive.
    Non-additive measures — ratios, averages, percentages — are not stored as fact
    columns; store the numerator and denominator and define the ratio as a metric.
12. **The SCD type is chosen, not defaulted.** Decide per dimension whether history
    matters and record why. Type 2 is a `snapshot` on the raw source; its `unique_key`,
    `strategy`, and `check_cols` can never be changed after the first run.

## Sources and contracts

13. **Every raw table enters through `sources:`.** No model selects from a hardcoded
    `database.schema.table`. `{{ source() }}` and `{{ ref() }}` are the only ways data
    enters a model — this is what makes lineage, `--select`, and state comparison work.
14. **Source freshness is declared, not assumed.** Every source that feeds a scheduled
    mart carries `loaded_at_field` and `freshness:` with `warn_after` / `error_after`.
    A source without a freshness block is an undocumented SLA.
15. **The source is quarantined at staging.** Renaming, casting, and coercion happen in
    exactly one staging model per source table. Nothing downstream references the raw
    column name.
16. **Public models carry a contract.** Any model consumed by another project, a BI tool,
    or a reverse-ETL job declares `contract: {enforced: true}` with column names and data
    types. A schema change that breaks a contract must fail the build, not the dashboard.
17. **PII is declared at the source and tagged at every model that carries it.** Masking,
    hashing, or exclusion happens in staging, not in the mart.

## Modeling

18. **One concept, one model.** A business concept is defined once and referenced
    everywhere. Two models computing "active customer" differently is a defect, not a
    variation.
19. **Layer discipline: staging → intermediate → marts.** Staging is 1:1 with a source
    and does no joins or aggregation. Intermediate holds reusable joins and heavy logic
    and is never exposed. Marts express business meaning and are the only layer a
    consumer touches.
20. **A model never references across a layer boundary backwards.** A mart does not
    `ref()` a source or another mart's internals; it references staging or intermediate
    models. Cross-mart references create hidden coupling — extract the shared logic to
    intermediate.
21. **Every model has a stated primary key**, tested with `unique` and `not_null`. If the
    grain has no single-column key, build a surrogate key with
    `dbt_utils.generate_surrogate_key` and test that.
22. **Materialization is a deliberate decision with a written reason.** View by default;
    table when it is queried more than it is built; incremental only when a full refresh
    is genuinely too slow or too expensive, and the cost is measured, not guessed.
23. **Incremental models must be idempotent and reproducible.** `unique_key` is set, the
    `is_incremental()` filter has an explicit lookback window sized to late-arriving data,
    and `dbt build --full-refresh` reproduces the same table. An incremental model whose
    full refresh differs from its incremental result is corrupt.
24. **Snapshots capture history that the source destroys.** Use a snapshot when a mutable
    source overwrites values you will need later. Snapshot the raw source, never a
    transformed model, and never change a snapshot's `unique_key` or strategy after the
    first run.
25. **`select *` does not survive into a mart.** Enumerate columns at every layer that a
    consumer reads, so a new upstream column cannot silently appear downstream.
26. **Logic that repeats three times becomes a macro.** Logic used once stays inline —
    a macro that hides a single simple expression makes the project harder to read.
27. **CTEs are named for what they contain**, imports at the top (`with source as (select
    * from {{ ref(...) }})`), a single `select` at the bottom. No subqueries nested more
    than one level.

## Testing

28. **No model merges without tests.** Minimum bar for every model: `unique` and
    `not_null` on the primary key. Add `relationships` on every foreign key, and
    `accepted_values` on every column with a closed domain.
29. **Test the business rule, not just the schema.** Every material assumption in the
    use-case spec becomes a test — a singular test, a `dbt_utils` test, or a unit test.
    An assumption nobody tests is a future incident.
30. **Unit tests cover the logic; data tests cover the data.** Any model with a CASE
    statement, window function, regex, date arithmetic, or non-trivial join gets a unit
    test with fixed inputs and fixed expected output. Data tests cannot catch a wrong
    formula that happens to produce plausible values.
31. **Severity is set intentionally.** `error` blocks the build; `warn` does not. A test
    that is permanently `warn` is either a real defect being ignored or a bad test —
    resolve it, do not leave it.
32. **Every failing test is reproducible.** `store_failures: true` on tests whose failures
    need investigating, so the offending rows land in a table rather than a log line.

## Documentation

33. **Description is the grain plus the meaning, not the model name restated.** "One row
    per order per fulfillment status; excludes internal test accounts" is documentation.
    "Orders table" is not.
34. **Every column exposed to a consumer has a description.** Shared definitions live in
    `docs` blocks and are referenced with `{{ doc() }}` so a metric's definition cannot
    drift between models.
35. **Assumptions are written down** in the model's description or the use-case spec, each
    with what breaks if it is wrong.

## Delivery and operations

36. **`dbt build`, not `dbt run` then `dbt test`.** `build` runs each model's tests
    immediately after the model and stops dependents when a test fails. Running all models
    then all tests propagates bad data through the whole DAG before anything fails.
37. **CI runs only what changed and its children** — `dbt build --select state:modified+`
    against a deferred production manifest. A CI job that rebuilds the whole project on
    every PR gets disabled by the team within a month.
38. **Production artifacts are stored, versioned, and retrievable.** `manifest.json`,
    `run_results.json`, and `sources.json` from the last production run are what state
    comparison, freshness monitoring, and performance analysis all read. No stored
    artifacts, no slim CI.
39. **Breaking changes are detected before merge, not after.** Removing or retyping a
    column on a contracted or referenced model requires a downstream impact check and
    either a version bump or a coordinated consumer update.
40. **Every deployment has a rollback path.** For a mart, that is the previous commit plus
    a `--full-refresh`; for an incremental model, it is the full-refresh cost stated in
    advance. A change with no rollback is not a release.
41. **Failures are diagnosed from artifacts, not from re-running blindly.** `run_results.json`
    has the error, the timing, and the node. Read it before changing code.

## Semantic layer

42. **A metric is defined once, in the semantic layer**, and every consumer reads it from
    there. A metric redefined in a BI tool is a second source of truth.
43. **Semantic models sit on marts, not on staging.** The semantic layer describes the
    business, and staging models describe a source system.
44. **Every semantic model declares its `primary_entity` or a primary entity column, its
    `defaults.agg_time_dimension`,** and the granularity of every time dimension. Missing
    granularity is the single most common MetricFlow validation failure.
45. **Metrics validate before they ship.** `dbt parse` then `mf validate-configs`, then
    `mf query` the metric and eyeball the number against a known-good SQL query.

## Working style

46. **Deliverables are files, not chat.** Write to `skill-packs/dbt-skills/use-cases/<slug>/` and to the dbt
    project, then summarize what changed and what needs a decision.
47. **Read the project before changing it.** `dbt_project.yml`, the existing layer
    conventions, the `packages.yml`, and the naming already in use decide how your model
    should look. Consistency with the project beats consistency with this document.
