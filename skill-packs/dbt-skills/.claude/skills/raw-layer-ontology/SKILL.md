---
name: raw-layer-ontology
description: Build the taxonomy and conceptual ontology from the raw layer BEFORE writing dbt models — map raw tables to business concepts, confirm natural keys, declare grains, derive entities/attributes/relationships traced to declared source columns, and produce the work list of models still to build. Use when a new source has landed and no models exist yet, when onboarding a use-case or connector, when asked "what should we model", "map these raw tables to concepts", "build the ontology first", "what entities are in this data", or before running dbt-model-design on a fresh raw layer.
---

# Raw-Layer Ontology

Every other ontology artifact here is derived from `manifest.json`, so it describes what
the dbt project **is**. This skill runs in the other direction: raw tables in, a
declaration of what the project **should build** out — which is the only direction
available before any model exists.

```
raw layer  ->  taxonomy.yml  ->  conceptual-model.json  ->  dbt models  ->  ontology/*.ttl
(declared)     (you decide)      (derived)                 (written)       (derived)
```

Rule 6 says the conceptual model precedes the physical one. Without an artifact that rule
is a good intention; `scripts/raw_taxonomy.py` makes it a file that later stages check
against.

## When this runs

After `analytics-request-framing` has written the use-case spec, and **before**
`dbt-model-design` or `connector-onboarding` writes any SQL. If models already exist,
this still works — `--plan` then reports near-zero gaps, and the diff is the backlog.

## The one thing you decide

The script derives everything except the semantics. Whether `tblCust01` is a Customer,
whether `Email` or `CustomerNumber` identifies it, and what one row means are judgements
no schema contains. Those live in `ontology/taxonomy.yml`, hand-authored, exactly the way
`connectors.yml` is — the catalogue written down once, the artifacts regenerated forever.

## Procedure

### 1. Read the raw layer and the spec

```bash
python3 scripts/raw_taxonomy.py --use-case <slug> --propose --format json
```

It reports, with evidence for every claim: concepts matched by name, natural-key
candidates ranked by how many mapped tables declare them, tables that matched nothing,
and tables excluded as pipeline bookkeeping.

**A source table with no `columns:` declared contributes no attributes.** If most tables
come back empty, stop and bootstrap the contracts first — the ontology is only as real as
the columns behind it:

```bash
python3 scripts/dbt_column_memory.py --use-case <slug> --emit-source-columns --write
```

### 2. Confirm the mappings — this is the actual work

Read `ontology/taxonomy.yml`. Every entry is a **name match**, nothing more. For each:

- **Is this table that concept?** Delete what is wrong. A wrong mapping is worse than a
  missing one, because it looks decided.
- **Which column is the natural key?** The proposal ranks by cross-source evidence: a
  column declared by four of five mapped tables is a far better candidate than one
  declared by a single table. Confirm the real one; it is often not the highest-ranked.
- **What is the grain?** One sentence — "one row per customer per tenant". Required.
  This is rule 4, and it is the field nothing can derive for you.
- **Which SCD type?** Rule 12: chosen, never defaulted. Leave it absent if genuinely
  undecided — absent is a state worth seeing.

Bring the unmatched tables to the user rather than guessing. Each is either a concept the
vocabulary lacks (add it to `ontology/ontology.yml`'s `concept_classes`) or genuinely out
of scope, and only someone who knows the domain can say which.

**Never invent a grain, a key, or a mapping to make the file look finished** (rule 5). An
entity you cannot complete is reported incomplete, and that report is the deliverable.

### 3. Derive the conceptual model

```bash
python3 scripts/raw_taxonomy.py --use-case <slug>
```

Writes `ontology/conceptual-model.json`: entities with their grain, keys, and kind;
attributes each traced to the source tables that declare them; proposed relationships;
concepts with no raw table behind them. Every problem it reports is a real gap in the
taxonomy — fix them and re-run until it exits 0.

Two fields are worth reading closely. `universal: false` on an attribute means only some
mapped sources declare it, which is where conformance breaks later. Entries under `gaps`
are concepts **this use-case's own `ontology.yml` declares** and no raw table supplies —
the highest-value output here, because it says what the data cannot answer yet. The shared
ERP/CRM vocabulary is reported separately as `shared_vocabulary_unused`, a count and a
capped sample: a concept nobody asked for is context, not a gap (rule 3).

### 4. Build from the plan, not from memory

```bash
python3 scripts/raw_taxonomy.py --use-case <slug> --plan
```

The work list: declared entities with no dbt model, each with its grain, its sources, and
its attribute count. Hand these to `dbt-model-design` one at a time. The grain is already
decided, so the model has one job.

### 5. Keep it current

```bash
python3 scripts/use_case_sync.py --use-case <slug> --stage taxonomy
python3 scripts/raw_taxonomy.py --use-case <slug> --check     # the gate
```

The `taxonomy` stage runs first in `use_case_sync`, before the manifest-derived stages,
because it is the only one that does not need a manifest.

## What this does not do

- **It does not write SQL.** `dbt-model-design` does, from the plan.
- **It does not replace the generated ontology.** `ontology_generator.py` still derives
  the Turtle from the manifest once models exist. This declares the target; that records
  the outcome; `--plan` is the difference.
- **It does not invent attributes.** An attribute is a column some mapped source table
  declares in `sources.yml`. Nothing else is admissible, which is why the artifact can be
  trusted by a stage that has no manifest to check it against.

## Related

- `analytics-request-framing` — the use-case spec, which runs before this
- `data-modeling` — the method for the judgements this skill collects (keys, grain, SCD,
  star-schema shape); read it when a mapping is genuinely hard
- `dbt-model-design` — consumes the plan
- `connector-onboarding` — the raw-to-staging scaffold for a new source
