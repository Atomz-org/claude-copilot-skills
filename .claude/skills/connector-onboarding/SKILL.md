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

**Declare the raw columns first.** They are the one input in a connector that cannot be
derived from anything else in the repository — every other column is a rename of them. Put
the ones you consume in the source's `columns:` block:

```yaml
      - name: articles
        columns:
          - name: id
          - name: name
```

A source contract states **what you depend on, not what the API returns**. Ten fields, not
forty. Upstream may then add fields freely, and removing one you declared becomes a
detectable breaking change rather than a warehouse error later.
`connector_alignment_check.py` raises `undeclared-source-column` when staging reads outside
it. For a connector already built, the list can be recovered instead of typed:
`dbt_column_memory.py --use-case <slug> --emit-source-columns --write`.

**Staging** quarantines the source — rename, cast, and coerce here and nowhere else
([rule 15](../../rules/analytics-engineering-rules.md)), every column enumerated
([rule 25](../../rules/analytics-engineering-rules.md)). Its job is to land the **contract's**
column names, which is why the contract is read before this is written and not after.

**Adapters** must match the other connectors' adapters for the same concept column for
column and in the same order. A missing column fails the `UNION ALL` at compile time and is
loud; a column in the **wrong position** with a compatible type unions cleanly and silently
transposes the data.

Do not reconstruct that contract by diffing files. It is already derived, from the SQL
rather than from documentation:

```bash
python3 scripts/dbt_column_memory.py --use-case <slug> --concept <dim_or_fact_name>
```

It answers three things at once, and the third is the one that saves the most time:

| | |
|---|---|
| the column list, **in order** | what your adapter must declare |
| `MISSING FROM <connector>` | a peer that already disagrees — do not copy it |
| `<connector> <Column> <- <source_table>.<raw_column> [renamed]` | which raw API field each existing connector mapped, resolved through the whole chain |

That last row is how you find out `dim_articles.ArticleName` comes from `Description` in
Fortnox — a mapping no column name anywhere in the project reveals.

Under the Graphify-first rule the same facts are in the code graph, so `graphify query
"column contract <concept>"` finds them during orientation without running anything.

Regenerating is automatic: a `PostToolUse` hook rebuilds the store when you edit a `.sql`
under a `dbt_project/`, incrementally, re-parsing only what changed.

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

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| `/new-connector stripe enhanza-analytics` | The project's own conventions detected and printed, then a dry-run scaffold |
| "onboard Fortnox" with no use-case slug | A stop, and `/new-use-case` — a connector needs a project to enter |
| "add HubSpot to the unified layer" | The source-aligned vs unified question settled before any file is written |

**Worked example**

> `/new-connector stripe enhanza-analytics`

```
Read first
  CONNECTORS.md, dbt_project.yml, staging/shopify/ (busiest existing connector), macros/registry.sql

Four questions, asked in one batch
  1. Raw tables?        customers, charges
  2. Unified layer?     yes — charges must reach fct_transactions
  3. Model names?       customers=dim_customers, charges=fact_transactions
  4. Currency?          [NEEDS INPUT] — not guessed
```

```bash
python3 scripts/new_connector.py stripe \
    --use-case enhanza-analytics \
    --tables customers=dim_customers,charges=fact_transactions \
    --unified-concepts dim_customers,fact_transactions \
    --dry-run
```

```
Detected conventions   staging infix __, source suffix _api, adapter prefix adapter_
                       ← check these against staging/shopify/ before re-running for real
Printed, not written   sources.yml block, registry entry, dbt_project.yml var + tags
                       ← paste by hand; a reviewer must see these three
```

```bash
# The check that matters: build alongside an existing connector, because a
# UNION ALL with one branch never tests the column contract
dbt build --select tag:unified+ \
  --vars '{"uid": "acme", "is_stripe_enabled": true, "is_shopify_enabled": true}'
```

If there is no warehouse or profile here, say which checks ran and which did not. An unrun
build is never reported as passing.
