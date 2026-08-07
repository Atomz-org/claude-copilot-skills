---
description: Build the taxonomy and conceptual ontology from the raw layer before any dbt model is written
argument-hint: <use-case slug> [and what the data is for]
---

Build the conceptual model for: **$ARGUMENTS**

Load the `raw-layer-ontology` skill. The artifacts are
`<use-case>/ontology/taxonomy.yml` (hand-authored) and
`<use-case>/ontology/conceptual-model.json` (derived).

---

## 1. Look before proposing

```bash
python3 scripts/raw_taxonomy.py --use-case <slug> --propose --format json
```

If most tables report `declared_columns: 0`, the raw layer has no column contracts and
the ontology would be entities with no attributes. Bootstrap them first:

```bash
python3 scripts/dbt_column_memory.py --use-case <slug> --emit-source-columns --write
```

If `ontology/taxonomy.yml` already exists the command refuses, on purpose — a name match
must never overwrite a decision. Edit the file instead.

## 2. Confirm the mappings with the user

Every proposal is a **name match**. Do not accept them silently. Bring the user:

- mappings you are unsure of, with the evidence beside them
- the ranked natural-key candidates per concept — cross-source evidence beats a
  single-table guess, and the top-ranked one is often still wrong
- the unmatched tables: a missing concept, or genuinely out of scope?

Then write `grain` for every entity — one sentence, "one row per X per Y" (rule 4).
Nothing derives it. **Do not invent one to make the file look finished** (rule 5); an
entity you cannot complete is reported incomplete, and that report is the point.

## 3. Derive, and fix what it reports

```bash
python3 scripts/raw_taxonomy.py --use-case <slug>
```

Exit 1 means real gaps: an attribute tracing to no declared column, a natural key no
source has, a missing grain. Fix the taxonomy and re-run until it exits 0.

## 4. Hand the plan to the model designer

```bash
python3 scripts/raw_taxonomy.py --use-case <slug> --plan
```

Declared entities with no dbt model yet, each with its grain and sources. Build them one
at a time with `/dbt-model` — the grain is already decided, so each model has one job.

## 5. Report

State: entities declared, raw tables mapped of declared, concepts with no source
(`gaps` — the most useful output, because it says what the data cannot answer yet), and
what is still to build. Name the decisions the user made, so the next session can see
that they were decisions rather than defaults.
