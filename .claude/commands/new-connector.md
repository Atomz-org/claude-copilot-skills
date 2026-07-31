---
description: Onboard a new source system into an existing use-case's dbt project, following that project's own conventions
argument-hint: <connector> --use-case <slug> --tables <t1,t2,...> [--unified-concepts ...] [--currency XXX]
---

Add this connector: **$ARGUMENTS**

Load the `connector-onboarding` skill. Scaffold with
[scripts/new_connector.py](../../scripts/new_connector.py), then commit through
[git-standard.sh](infra/git-standard.sh).

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

## 6. Commit through the git skill

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
