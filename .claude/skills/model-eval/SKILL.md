---
name: model-eval
description: Extract the dbt models the ontology declares but the project never built, then evaluate them end to end on DuckDB against what the ontology promised — column contract, declared enums, PII exclusion, and per-supplier attribution. Use when asked "which models are we missing", "generate models from the ontology", "test these models on sample data", "do the marts match the ontology", before wiring a BI dashboard or an agentic report over a use-case, or when a number in a report cannot be attributed to a connector.
---

# Model Eval

Two scripts, one direction. `ontology_to_dbt.py` writes the business-layer models the
ontology declares and the project never built; `eval_dbt_models.py` builds each one on
DuckDB from the sample seeds and asks the database the questions the ontology already
answered on paper.

```
index.json + column-annotations.json ─ ontology_to_dbt ─ logic_bi_*.sql
                                                             │
                       sample seeds ─ dbt_sample_build ─ DuckDB ─ eval_dbt_models
```

Measured on enhanza-analytics: **58 concepts, 27 with an `erp_bi_*` union, 8 with a
business model.** Nineteen unions had no consumer-facing model and nothing said so, because
a model that does not exist produces no lineage, no test, and no error.

## When this runs

After `annotations` — the generator carries only columns whose meaning is recorded, so an
unannotated concept produces nothing and is reported as blocked. Before any BI or agentic
report work: this is what says whether the numbers those would read are attributable.

## Procedure

### 1. See the gap

```bash
python3 scripts/ontology_to_dbt.py --use-case <slug> --dry-run
```

Concepts with a union and no business model, richest evidence first. A concept listed under
`blocked on annotation` has no recorded column meanings — annotate it first
(`column-annotation`), because a model of one column is not a model.

### 2. Write the models

```bash
python3 scripts/ontology_to_dbt.py --use-case <slug> --write
./skill-packs/dbt-skills/use-cases/<slug>/artifacts/refresh.sh    # re-parse
```

What lands is a faithful projection, never invented business logic: the conformed columns
whose meaning is recorded, under the names conformance already agreed, gated on the
supplier list the ontology holds. Direct-PII columns are withheld ([rule 17]) and counted.
Tests come from the facets — `not_null` on identifiers, `accepted_values` on a domain that
cited its source — and **no `unique`**, because no grain is declared for these concepts and
asserting a key nobody chose is the invention [rule 5] forbids.

### 3. Evaluate on DuckDB

```bash
python3 scripts/eval_dbt_models.py --use-case <slug>
python3 scripts/eval_dbt_models.py --use-case <slug> --model logic_bi_dim_company
python3 scripts/eval_dbt_models.py --use-case <slug> --format json --check
```

Every expectation is labelled from the ontology, never read off the relation being judged.
A concept the sample seeds cannot reach is `no-sample`; a failure in an upstream staging
model is `upstream-unbuildable`. Neither is scored — an eval that blames the generator for
an absent CSV gets switched off within a week, taking the real findings with it.

## Reading the report

Failures are classified, never just counted. `contract-miss` on four models and
`attribution-gap` on one are two different bugs with two different owners.

| Class | What it means |
|---|---|
| `contract-miss` / `contract-extra` | the built relation and the ontology disagree on columns |
| `null-identifier` | an identifier column contains NULLs |
| `domain-violation` | a value outside a declared enum — the enum is wrong, or the data is |
| `pii-leak` | a `pii: direct` column reached a consumer-facing model |
| `attribution-gap` | an enabled supplier contributed no rows |
| `label-mismatch` | the supplier contributed under a `DataSource` value that is not the ontology's label |
| `ambiguous-sql` | an unqualified column with several tables in scope: BigQuery resolves it, DuckDB refuses |
| `no-sample`, `upstream-unbuildable` | reported, not scored |

`label-mismatch` is the one worth understanding before building a report: the ontology
publishes `Visma eAccounting` and the union writes `Visma e-Accounting`, so an agent
filtering by the published name gets **zero rows and no error**. That failure mode is
invisible to dbt, to the alignment checker, and to a human reading either.

## What this does not do

- **It does not invent business logic.** The hand-written models rename and concatenate
  (`Description || ' (' || Code || ')'`); a generator guessing at that ships plausible
  columns nobody asked for.
- **It does not fix what it finds.** `ambiguous-sql` and `label-mismatch` are defects in the
  project, reported with the evidence; whose they are is a decision.
- **It does not replace dbt tests.** A test asserts one thing per column inside the build;
  the eval asks cross-cutting questions a test cannot — did every supplier contribute, did a
  column nobody declared appear.

## Related

- `column-annotation` — the recorded meanings this generator projects; run it first
- `raw-layer-ontology` — the other direction, before any model exists
- `wren-genbi` — the serving tier these models feed

[rule 5]: ../../rules/analytics-engineering-rules.md
[rule 17]: ../../rules/analytics-engineering-rules.md
