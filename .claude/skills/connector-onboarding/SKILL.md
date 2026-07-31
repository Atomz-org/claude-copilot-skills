---
name: connector-onboarding
description: Onboard a new source system (Shopify, HubSpot, NetSuite, Spiris, Fortnox, Tripletex, …) into an existing use-case's dbt Core project. Detects the project's own connector conventions and follows them, scaffolds staging/adapter/source-aligned models from the connector's raw tables, and finishes through the repository git skill. Use when asked to "add a connector", "onboard <system>", "connect <system> to <use-case>", or when a new upstream API needs to reach an existing DAG.
---

# Adding a connector to an existing use-case

A connector is not "some new models". It is a new **upstream system** entering a dbt project
that already has conventions, existing connectors, and — in a multi-tenant project — a
registry that decides what exists for a given run.

The job: read how this project already does it, follow that, and leave the contract files as
a hand-written diff a reviewer can actually review.

## What this skill will not do

- **Invent** a table name, a column, a currency, or a freshness SLA. Mark `[NEEDS INPUT]`
  and keep going ([rule 5](../../rules/analytics-engineering-rules.md)).
- **Create the use-case.** If the slug does not exist, stop and run `/new-use-case`
  ([rule 1](../../rules/analytics-engineering-rules.md)).
- **Impose a layout.** If the project names models `stg_shopify__customers`, the new
  connector gets `stg_stripe__charges`, not whatever this document shows.
- **Commit to `main`/`master`,** or push without being asked.

---

## 1. Read the project before writing to it

```bash
ls skill-packs/*/use-cases/
cat skill-packs/*/use-cases/<slug>/CONNECTORS.md 2>/dev/null
ls skill-packs/*/use-cases/<slug>/dbt_project/models/staging/
```

Read `dbt_project.yml` (layers, tags, vars), the `sources.yml`, one existing connector's
staging directory, and the macros directory for a registry. **The project's own conventions
outrank anything written here** ([rule 47](../../rules/analytics-engineering-rules.md)).
Detail: [references/conventions.md](references/conventions.md).

## 2. Settle four things, in one batch

Ask only for what the request did not already say, and ask them together.

1. **Which raw tables?** Each becomes one source table and one staging model. The source is
   `<connector>_api`, resolving to schema `<connector>_api_<uid>` — unless the project
   already does otherwise.

2. **Unified layer, or source-aligned only?** The expensive question, and easy to get wrong
   for a system that is not an ERP.

   | | Cost | When |
   |---|---|---|
   | Source-aligned only | staging + one model per table | no equivalent in the common schema, or nobody has asked for it unioned |
   | Unified participation | an adapter per concept, columns matching every other connector's adapter **exactly and in order** | its rows must reach the shared facts and the marts |

   A CRM or e-commerce system joining an ERP-shaped unified layer will pad much of the
   common schema with typed nulls. That is normal — read the existing CRM connector before
   concluding the cost is too high.

3. **What is each staging model called?** Whether raw `customers` becomes `dim_customers`
   is a modeling decision, not a naming convention. State it; the scaffold will not guess.

4. **Default currency**, if the project tracks one. Omit rather than guess: NULL is visible,
   a wrong code silently mis-values every row the connector contributes.

## 3. Scaffold, dry-run first

```bash
python3 scripts/new_connector.py <connector> \
    --use-case <slug> \
    --tables customers=dim_customers,orders=fact_orders \
    --unified-concepts dim_customers,fact_orders \
    --currency USD \
    --dry-run
```

**Read the detected conventions it prints.** They are inferred from the project's busiest
existing connector, and inference can be wrong — that is why it prints them instead of
assuming. Override with `--staging-infix`, `--adapter-infix`, or `--source-suffix` when the
detected shape disagrees with step 1. Then re-run without `--dry-run`.

`--tables` takes `table=model` where the model name differs from the raw table name. Every
`--unified-concepts` entry needs a matching model, because an adapter reads its own
connector's staging model.

Existing files are never overwritten; everything written is a stub carrying `[NEEDS INPUT]`.

## 4. Paste the contract files by hand

The script prints — and deliberately does not write — the source definition, the registry
entry, and the `dbt_project.yml` var and tags. These three are what a reviewer must actually
see; generated config gets skimmed.

- **The connector key is string-matched, never resolved.** Registry key, `is_<key>_enabled`
  var, `staging/<key>/` directory, and the filename prefix must be the same string. A
  mismatch produces silence, not an error.
- **Declare `loaded_at_field` and `freshness`**
  ([rule 14](../../rules/analytics-engineering-rules.md)). Without them a dead connector is
  indistinguishable from a quiet one.

## 5. Write the models

**Staging** quarantines the source — rename, cast, and coerce here and nowhere else
([rule 15](../../rules/analytics-engineering-rules.md)), every column enumerated
([rule 25](../../rules/analytics-engineering-rules.md)).

**Adapters** must match the other connectors' adapters for the same concept column for
column and in the same order. Diff against an existing one. A missing column fails the
`UNION ALL` at compile time and is loud; a column in the **wrong position** with a
compatible type unions cleanly and silently transposes the data.

**Union models need no edit** in a registry-driven project — that is what the registry is
for. If a concept has no union model because no connector supplied it before, create one.

## 6. Verify, document, commit

Full matrix and the definition of done:
[references/verification.md](references/verification.md).

The short version — the check that actually matters is building the new connector
**alongside an existing one**, because a `UNION ALL` with one branch never tests the column
contract:

```bash
python3 -m pytest tests/ -q
cd skill-packs/<pack>/use-cases/<slug>/dbt_project
dbt build --select tag:<unified>+ \
  --vars '{"uid": "<tenant>", "is_<connector>_enabled": true, "is_<existing>_enabled": true}'
```

`dbt build`, not `dbt run` then `dbt test`
([rule 36](../../rules/analytics-engineering-rules.md)). If dbt cannot run here — no
warehouse, no profile — **say so plainly** and report which checks did and did not run.
Never describe an unrun build as passing.

Then commit through the git skill. Load `git-commit-quality`; never commit to `main` or
`master`:

```bash
git switch -c feat/<ticket>-<connector>-connector
git add -A
bash .claude/commands/infra/git-standard.sh \
    "feat(<connector>): add <Display> connector to <use-case>"
```

`git-standard.sh` enforces the branch pattern and Conventional Commits and refuses on
`main`/`master`. It wraps `git commit` only — staging is yours. **Push and open a PR only
when asked**; then `git push -u origin HEAD`, `/pr-ready`, `/review`.

## Rules that bind here

[Rules 1, 5](../../rules/analytics-engineering-rules.md) (use-case first, never invent),
[13–15](../../rules/analytics-engineering-rules.md) (sources, freshness, staging
quarantine), [19–21, 25](../../rules/analytics-engineering-rules.md) (layer discipline,
stated PK, no `select *`), [28, 33](../../rules/analytics-engineering-rules.md) (tests,
documentation), [36, 40, 47](../../rules/analytics-engineering-rules.md) (`dbt build`,
rollback, read the project first).
