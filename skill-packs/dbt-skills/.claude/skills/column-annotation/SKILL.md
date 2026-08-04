---
name: column-annotation
description: Record what each conformed column MEANS — its role, whether SUM() over it is meaningful (additivity), its PII class, its unit, and its closed domain — then project that into the ontology and the WrenAI knowledge the BI and MCP layers read. Use after a column contract exists, when asked "can I sum this", "is this column PII", "what does this column mean", "what values can this take", before building a dashboard or a metric on an unfamiliar column, or when an agent needs to write correct SQL against a conformed concept.
---

# Column Annotation

`column-memory.json` says which raw column feeds which conformed column — the lineage.
Nothing in a dbt project says what the conformed column **is**, and three binding rules
need exactly that: additivity per measure ([rule 11]), PII declared and tagged
([rule 17]), `accepted_values` on every closed domain ([rule 28]).

The consequence is concrete rather than theoretical. `QuantityInStock` and `SalesValue`
are both `float64` measures, and an agent reading a bare column list will sum both. One of
those answers is right and the other is a stock level added across time.

```
column-memory.json ─ annotations.yml ─ column-annotations.json ─┬─ column-semantics.ttl
   (lineage)          (you decide)         (derived)            ├─ index.json
                                                                └─ wren/knowledge/
```

## When this runs

After `columns` has produced a column contract, and before anything that aggregates:
a metric, a dashboard, an MCP client answering a business question. It is stage
`annotations` in `use_case_sync.py`, sequenced between `columns` and `ontology`.

## The one thing you decide

Additivity and PII are not in any schema. A cast type says `float64`; it does not say
whether summing across time is meaningful. That judgement lives in
`ontology/annotations.yml`, hand-authored — the same split as `connectors.yml` and
`taxonomy.yml`.

## Procedure

### 1. Bootstrap what the project already evidences

```bash
python3 scripts/column_annotations.py --use-case <slug> --propose --evidenced-only
```

Emits only the columns whose every facet is already backed: a description the project
wrote in its own `schema.yml`, a role derived from a cast or a name shape, and — where the
column is a measure — an additivity that followed from its definition. That file builds
with zero problems on the first run.

Drop `--evidenced-only` to see every candidate including the incomplete ones. Either form
**refuses to overwrite** an existing `annotations.yml`: a derived candidate must never
overwrite a confirmed decision.

### 2. Work the backlog — this is the actual work

```bash
python3 scripts/column_annotations.py --use-case <slug> --coverage
```

Ranked by how many connectors carry each column, so a reviewer who stops halfway has spent
the time where it counts. For each column bring the user the evidence, not a verdict:

- **Role.** identifier, measure, dimension, timestamp, flag, or text.
- **Additivity, for every measure.** `additive` (a flow — sums across every dimension),
  `semi_additive` (a level — sums across everything except time), `non_additive` (a ratio,
  a rate, or a **unit price**; storing one as a fact column is what [rule 11] forbids).
  There is no default. A measure with no additivity is a `problem`, not an assumption.
- **PII class.** `direct` names a person alone; `quasi` re-identifies in combination;
  `indirect` identifies through a join. Three classes rather than a flag, because the
  remedies differ.
- **Definition.** One sentence saying what the column means. Harvested from the project's
  own `schema.yml` where one exists; **never paraphrased into existence** where it does not
  ([rule 5]). A column with no description stays out of the file.
- **Closed domain, if any.** Every value, plus the source they came from. An enum nobody
  can cite is invented, and a wrong one passes every `accepted_values` test — because it
  generated them.

A column you cannot complete is left out. Absent means unannotated, which is honest;
a filled-in guess means annotated, which is not.

### 3. Derive and project

```bash
python3 scripts/use_case_sync.py --use-case <slug> --stage annotations --stage ontology
python3 scripts/use_case_sync.py --use-case <slug> --stage wren
```

The artifact is `ontology/column-annotations.json`. From it: RDF in
`ontology/topology/column-semantics.ttl`, the `column_semantics` record list in
`index.json` (which backs the `describe_column` MCP tool), and two knowledge files under
`wren/knowledge/` — the aggregation contract and the personal-data caveat.

### 4. Gate it

```bash
python3 scripts/column_annotations.py --use-case <slug> --check
```

Exit 1 on a stale artifact or on any of the four refusals: a measure with no additivity, a
closed domain with no source, a placeholder definition, or an annotation naming a column
that no longer exists.

## Reading the output

- **`Never SUM these`** in `column-semantics.md` is the part an agent cannot infer from a
  name. Check it before writing an aggregate.
- **`unannotated`** is a real number, not a rounding error. A column absent from the
  artifact has no recorded meaning — treat its additivity and PII class as unknown rather
  than assuming defaults.
- **`abstained`** in a proposal means the deriver found conflicting evidence and said so.
  An inflated annotation is worse than an honest gap: the gap gets filled, the guess gets
  trusted.

## What this does not do

- **It does not annotate per model.** Conformance already asserts a column means the same
  thing in every connector that supplies it, so the annotation belongs to the conformed
  column. Per-model annotation would let one column be a measure in one connector and a
  dimension in another — the drift the conformed layer exists to prevent.
- **It does not generate `accepted_values` tests.** It records the domain and its source;
  turning that into a test is `analytics-quality-guardian`'s call.
- **It does not mask anything.** It says which columns carry personal data and of what
  class. The masking happens in staging ([rule 17]).

## Related

- `raw-layer-ontology` — the taxonomy and conceptual model, upstream of this
- `data-modeling` — grain and measure design, which is what additivity depends on
- `wren-genbi` — the serving tier that consumes the projected knowledge files

[rule 5]: ../../rules/analytics-engineering-rules.md
[rule 11]: ../../rules/analytics-engineering-rules.md
[rule 17]: ../../rules/analytics-engineering-rules.md
[rule 28]: ../../rules/analytics-engineering-rules.md
