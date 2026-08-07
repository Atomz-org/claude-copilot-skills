---
description: Record what each conformed column means — role, additivity, PII class, unit, domain — and project it into the ontology and the WrenAI knowledge layer
argument-hint: <use-case slug> [column or concept to start with]
---

Annotate the conformed columns of: **$ARGUMENTS**

Load the `column-annotation` skill. Derive with
[scripts/column_annotations.py](../../../scripts/column_annotations.py). The artifacts are
`<use-case>/ontology/annotations.yml` (hand-authored) and
`<use-case>/ontology/column-annotations.json` (derived).

---

## 1. Bootstrap, then look at what is missing

```bash
python3 scripts/column_annotations.py --use-case <slug> --propose --evidenced-only
python3 scripts/column_annotations.py --use-case <slug> --coverage
```

The first writes only the columns the project already evidences and refuses to overwrite an
existing file. The second ranks the backlog by how many connectors carry each column.

If the run skips with "no ontology/column-memory.json", the column contract does not exist
yet — build it first with `--stage columns`.

## 2. Bring the user evidence, never a verdict

For each column in the backlog, present what was found and ask for the call:

- **additivity for every measure** — additive (a flow), semi-additive (a level, does not
  sum across time), non-additive (a ratio, a rate, or a unit price). There is no default;
  [rule 11](../../rules/analytics-engineering-rules.md) wants the decision recorded.
- **PII class** — direct, quasi, or indirect
  ([rule 17](../../rules/analytics-engineering-rules.md)). Three classes, because the
  remedies differ.
- **closed domain** — every value **and the source**. An enum nobody can cite is invented
  ([rule 5](../../rules/analytics-engineering-rules.md)), and a wrong one passes every
  `accepted_values` test it generates.
- **definition** — harvested from the project's own `schema.yml` where one exists. Do not
  paraphrase one into existence; a column nobody described stays out of the file.

A column you cannot complete is **left out**, not filled in. Absent means unannotated.

## 3. Derive and project

```bash
python3 scripts/use_case_sync.py --use-case <slug> --stage annotations --stage ontology
python3 scripts/use_case_sync.py --use-case <slug> --stage wren
```

This is the step that makes the annotation reach a consumer: RDF in
`ontology/topology/column-semantics.ttl`, `column_semantics` in `index.json` (backing the
`describe_column` MCP tool), and `wren/knowledge/rules/column-semantics.md` plus
`wren/knowledge/caveats/pii.md` — the files an agent reads before it writes SQL.

## 4. Gate

```bash
python3 scripts/column_annotations.py --use-case <slug> --check
```

## 5. Report

State: columns annotated of conformed, how many carry PII and of which class, how many may
not be summed the way their names suggest, and what is still unannotated. Name the
decisions the user made — additivity and PII are judgements, and the next session needs to
see that they were decided rather than defaulted.
