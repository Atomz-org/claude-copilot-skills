---
description: Onboard a new source system into an existing use-case's dbt project, following that project's own conventions
argument-hint: <connector> --use-case <slug> --tables <t1,t2,...> [--unified-concepts ...] [--currency XXX]
---

Add this connector: **$ARGUMENTS**

Load the `connector-onboarding` skill. Scaffold with
`scripts/new_connector.py` at the repository root, then commit through
`.claude/commands/infra/git-standard.sh`.

---

## 1. Read the project before writing to it

A connector joins a project that already has conventions. Find the use-case and read how it
already does this — its layout wins over any example in the skill.

```bash
ls skill-packs/*/use-cases/
cat skill-packs/*/use-cases/<slug>/CONNECTORS.md 2>/dev/null
ls skill-packs/*/use-cases/<slug>/dbt_project/models/staging/
```

**If the use-case does not exist, stop.** Run `/new-use-case` first — a connector belongs to
a framed use-case, and a dbt project with no spec is [rule 1](../rules/analytics-engineering-rules.md).

## 2. Settle four things, in one batch

Ask only for what the request did not already say. Ask them together.

1. **Which raw tables?** Each becomes a source table and one staging model. The source is
   `<connector>_api`, resolving to `<connector>_api_<uid>` — unless the project does
   otherwise, in which case do what the project does.
2. **Unified layer, or source-aligned only?** Unified participation means an adapter per
   concept whose columns match every other connector's adapter for that concept exactly and
   in order. Source-aligned only means staging plus a per-table model, and no adapter.
3. **What is each staging model called?** Whether raw `customers` becomes `dim_customers`
   is a modeling decision. State it — the scaffold will not guess it.
4. **Default currency**, if the project tracks one. Omit rather than guess: NULL is visible,
   a wrong code silently mis-values every row.

**Never invent** a table name, a column, a currency, or a freshness SLA. Mark `[NEEDS INPUT]`
and keep going ([rule 5](../rules/analytics-engineering-rules.md)).

## 3. Scaffold, dry-run first

```bash
python3 scripts/new_connector.py <connector> \
    --use-case <slug> \
    --tables customers=dim_customers,orders=fact_orders \
    --unified-concepts dim_customers,fact_orders \
    --dry-run
```

**Read the detected conventions it prints.** They are inferred from the project's busiest
existing connector; inference can be wrong, which is why it prints them rather than
assuming. Override with `--staging-infix`, `--adapter-infix`, or `--source-suffix` when the
detected shape disagrees with what you read in step 1. Then re-run without `--dry-run`.

The script writes stubs only, never overwrites, and deliberately does **not** edit
`sources.yml`, the registry, or `dbt_project.yml`. It prints those three to paste by hand —
they are the connector's contract, and a reviewer must see them as a hand-written diff.

## 4. Write the columns

Staging quarantines the source: rename, cast, coerce here and nowhere else, every column
enumerated ([rules 15, 25](../rules/analytics-engineering-rules.md)).

Adapters must match the other connectors' adapters for the same concept **column for column
and in order**. Diff against an existing one. A missing column fails at compile time and is
loud; a column in the wrong position with a compatible type unions cleanly and silently
transposes the data.

Union models need no edit in a registry-driven project — that is what the registry is for.

## 5. Verify

Three passes, in this order. The order is the point: each one needs something the previous
one produced, and running them out of order reports a symptom instead of the cause.

**5a — alignment, no warehouse.** Needs no profile and no parse, so it runs anywhere and
catches the defects that otherwise surface later as an unrelated-looking failure:

```bash
python3 scripts/connector_alignment_check.py \
    --use-case <slug> --connector <connector> --check
```

Catches a hardcoded `FROM`, a staging directory with no registry entry, a missing
`is_<connector>_enabled` default, a source block with no freshness, and generic-test syntax
the project's pinned dbt cannot parse. That last one matters: a single schema.yml using the
dbt 1.10 `arguments:` nesting made `dbt parse` fail for all 359 models in
enhanza-analytics, and the error named a test rather than the syntax.

**5b — parse, then check against every other model.** Steps 5a's checks only ever look at
the new connector's own files. Whether it *conflicts* with what is already in the project
can only be answered from a manifest, so the parse comes first:

```bash
./skill-packs/<pack>/use-cases/<slug>/artifacts/refresh.sh   # parses with all connectors on

python3 scripts/connector_alignment_check.py \
    --use-case <slug> --connector <connector> \
    --manifest skill-packs/<pack>/use-cases/<slug>/dbt_project/target/manifest.json --check
```

With `--manifest` the run compares the connector against **every model in the project** and
reports the collisions it participates in. This is what catches a new
`<connector>_bi_dim_customers` landing in a dataset that already owns `dim_customers` —
`model_alias()` strips the connector prefix, so two models an entire layer apart can claim
one relation, and dbt then refuses to build either.

With `sqlglot` installed it also compares your adapter's **columns** against the other
adapters for the same ERP concept. Column-level drift is invisible to a single-connector
build: `erp_union()` stacks one adapter per enabled source, so a missing column only breaks
the union when two connectors are on at once. Before writing the adapter, read what the
existing ones map:

```bash
python3 scripts/dbt_column_lineage.py \
    --manifest skill-packs/<pack>/use-cases/<slug>/dbt_project/target/manifest.json \
    --column <ConformedColumnName>
```

**5c — the build.**

```bash
python3 -m pytest tests/ -q

cd skill-packs/<pack>/use-cases/<slug>/dbt_project
dbt build --select tag:<connector> --vars '{"uid": "<tenant>", "is_<connector>_enabled": true}'

# the one that actually matters:
dbt build --select tag:<unified>+ \
  --vars '{"uid": "<tenant>", "is_<connector>_enabled": true, "is_<existing>_enabled": true}'
```

A `UNION ALL` with one branch never tests the column contract. The connector alone passes
while being structurally incompatible with every other one. If dbt cannot run here, **say
so** and report which checks did and did not run.

## 6. Register the connector in the catalogue

A connector is not on the platform until `ontology/connectors.yml` says so. Add the row —
`status: planned` while the models are stubs, `implemented` once they are real:

```yaml
  - key: <connector>
    name: <Display Name>
    kind: erp          # erp | crm | commerce
    region: <ISO>      # omit rather than guess
```

The catalogue and the dbt registry must agree, and the generator fails if they do not: a
connector in `all_available_sources` with no catalogue row, or a row marked `implemented`
that the registry has never heard of, are both reported by name. That is the check that stops
the ontology describing a platform that no longer exists.

If the connector supplies a concept the shared ERP/CRM vocabulary does not classify, the
generator reports it rather than guessing. Add it to `concept_classes` in
`ontology/ontology.yml` — that is where a domain's own concepts live, not in the shared map.

## 7. Sync everything derived

One command covers the ontology, its machine index, the sample seeds, the graph merge, and
the alignment verdict — in dependency order, each reporting `ok`, `changed`, or `skip` with
a reason:

```bash
python3 scripts/use_case_sync.py --use-case <slug> --graphify-update
```

The graph merge is what makes the new models reachable in `graphify`, which has no SQL
parser: without the manifest's edges a `.sql` file contributes no symbols at all. The
ontology stage is what stops the vocabulary and the warehouse drifting apart — skipping it
leaves classes asserting `conn:dbtModel` for models that were just renamed.

**Never run `graphify update` after this command.** The AST rebuild drops every `.sql` node,
so a rebuild after the merge deletes the whole dbt DAG while leaving a graph that still looks
populated. `--graphify-update` sequences the rebuild *before* the merge, which is why it is a
flag here rather than a second command.

`refresh.sh` parses with **every** connector enabled, which matters more than it looks: this
project gates each connector behind `is_<source>_enabled`, all defaulting to false, so a
parse with defaults produces a manifest holding a fraction of the project. The emitter's
coverage gate is what stops that fraction becoming the graph.

## 8. Commit through the git skill

Load `git-commit-quality`. Not on `main` or `master`.

```bash
git switch -c feat/<ticket>-<connector>-connector
git add -A
bash .claude/commands/infra/git-standard.sh \
    "feat(<connector>): add <Display> connector to <use-case>"
```

Keep the mechanical scaffold and the hand-written column mapping in separate commits where
practical — reviewing them together hides the second in the first.

**Push only when asked.** Then `git push -u origin HEAD`, `/pr-ready`, `/review`.

---

## Rules that bind here

[Rules 1, 5](../rules/analytics-engineering-rules.md) (use-case first, never invent);
[13–15](../rules/analytics-engineering-rules.md) (sources, freshness, staging
quarantine); [21, 25, 28](../rules/analytics-engineering-rules.md) (stated PK, no
`select *`, tests); [36, 40, 47](../rules/analytics-engineering-rules.md) (`dbt build`,
rollback, read the project first).

## Output

Write the files, then summarize in chat:

- the connector, the use-case, and the conventions that were detected;
- which layers it reaches — source-aligned only, or unified, and which concepts;
- what was pasted by hand versus scaffolded;
- what is `[NEEDS INPUT]` and who can answer it;
- which verification actually ran, and which could not;
- the rollback path, and the next command (`/dbt-test`, `/pr-ready`).
