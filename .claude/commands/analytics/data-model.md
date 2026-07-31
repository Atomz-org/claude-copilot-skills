---
description: Design the data model for a subject area — entities, ERD, keys, grain, bus matrix, star schema
argument-hint: <subject area or business process>
---

Design the data model for: **$ARGUMENTS**

Load the `data-modeling` skill. Write to `use-cases/<slug>/`:

- [templates/data-model-canvas.md](../../../templates/data-model-canvas.md) — one per subject area
- [templates/bus-matrix.md](../../../templates/bus-matrix.md) — if more than one business process
- [templates/star-schema-spec.md](../../../templates/star-schema-spec.md) — one per business process

---

## 0. Precondition

A use-case spec must exist. If it does not, stop and run `/new-use-case` first — a data
model with no named decision and no named consumer is speculative work, and this is where
that becomes expensive rather than cheap.

If a canvas already exists for this subject area, **extend it**. A second canvas for the
same area is how two definitions of "customer" get created.

## 1. Read the project first

```bash
dbt ls --resource-type model --output name 2>/dev/null
python scripts/erd_generator.py --manifest target/manifest.json --layer marts
python scripts/dimensional_model_validator.py --manifest target/manifest.json
```

The existing dimensions decide your work. A dimension that already exists is one you
**conform to**, not one you rebuild — check the ERD before adding anything.

## 2. Conceptual — entities and events

Pull the nouns and verbs out of the use-case spec. Filter the nouns with both tests:

1. Can it exist before and after the relationship?
2. Does the business ask questions "by" it?

Nouns that survive are entities (→ dimensions). Verbs the business measures are events
(→ facts). Record the **rejected** candidates too — they come back.

Draw the ERD with explicit cardinality **and optionality**. Review it with the requester.
Prose gets nodded at; an arrow gets argued about, which is the point.

## 3. Logical — keys, attributes, grain

Per entity: business key, whether it is stable, whether a surrogate is needed and why,
the attribute list, the SCD type, and the source of truth per attribute.

Never hash a mutable attribute into a key. When it changes, every downstream join breaks
and no test catches it, because both sides stay internally consistent.

Fill the grain matrix — one sentence per model, with its primary key.

## 4. Bus matrix

If there is more than one business process, fill it in. Then read it **down the columns**:
any dimension used by two processes must have one definition, one key, one table.

A conformance conflict is a blocker, not a note. Resolve it to one of: one dimension, two
dimensions with distinct non-ambiguous names, one dimension plus a bridge, or one
dimension role-played. Name who decided.

## 5. Star schema spec, per process

Kimball's four steps **in order**: process → grain → dimensions → measures. Choosing
measures before declaring the grain produces a table whose grain is whatever the join
happened to produce.

Then check every measure against the grain sentence. A measure true at a coarser grain
will be double-counted — it belongs in a different fact.

Record additivity per measure. Ratios and averages are **not** stored fact columns; store
numerator and denominator and define the ratio as a metric.

## 6. Ask, don't assume

Ask only the questions whose answers change the model — usually the grain, the
optionality of a key relationship, and whether history matters. Ask them **in one batch**.

**Never invent** an entity, a key, a cardinality, or a business definition. Mark it
`[NEEDS INPUT]` and keep designing around it.

## 7. Hand off

Each row of the grain matrix becomes a
[model blueprint](../../../templates/model-blueprint.md), then `dbt-model-design` writes the
SQL. Do not write SQL from this command.

---

## Rules that bind here

[Rules 6–12](../../rules/analytics-engineering-rules.md): conceptual model before physical;
one entity, one definition, one table; cardinality and optionality are explicit; keys are
never hashed from mutable attributes; grain is declared per table before columns;
additivity is recorded per measure; the SCD type is chosen, not defaulted.

Plus [rules 1, 4, 5](../../rules/analytics-engineering-rules.md): no model before a spec,
declare the grain, never invent a name.

## Output

Write the files, then summarize in chat:

- the entity list, and what was rejected as an attribute rather than an entity;
- the ERD, as a Mermaid block;
- the grain of every table the model produces;
- conformance conflicts, with who must resolve each;
- what is `[NEEDS INPUT]`;
- the next command (`/dbt-model <first model>`), in build order — shared dimensions first.
