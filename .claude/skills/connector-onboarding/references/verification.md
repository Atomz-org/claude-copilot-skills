# Verifying and shipping a connector

## The check that actually matters

```bash
dbt build --select tag:<unified>+ \
  --vars '{"uid": "<tenant>", "is_<connector>_enabled": true, "is_<existing>_enabled": true}'
```

**A `UNION ALL` with one branch never tests the column contract.** Build the new connector
on its own and it passes while being structurally incompatible with every other connector in
the project. The adapter is unverified until it is built alongside at least one existing
connector.

Worse, the failure is asymmetric:

| Defect | Behaviour |
|---|---|
| Column missing from the adapter | fails at compile time — loud, easy |
| Column present but in the **wrong position**, compatible type | unions cleanly, silently transposes the data |

Only a column-by-column diff against an existing adapter catches the second.

## Full matrix

| Check | Command | Catches |
|---|---|---|
| Repository invariants | `python3 -m pytest tests/ -q` | registry/model drift, missing scaffolding |
| Parse | `dbt parse --vars '{"uid": "<t>", "is_<c>_enabled": true}'` | Jinja and ref errors |
| Connector alone | `dbt build --select tag:<connector> --vars '{...}'` | staging SQL, source resolution |
| **Connector unioned** | `dbt build --select tag:<unified>+ --vars '{... two connectors ...}'` | **adapter column contract** |
| Freshness | `dbt source freshness --select source:<connector>_api` | whether the SLA is real |
| Disabled | `dbt build --select tag:<unified>+` with the connector **off** | that the connector is genuinely optional |

`dbt build`, not `dbt run` then `dbt test` — build runs each model's tests immediately and
stops dependents when one fails, instead of propagating bad data through the whole DAG
([rule 36](../../../rules/analytics-engineering-rules.md)).

**If dbt cannot run here** — no warehouse credentials, no profile — say so plainly and
report which checks did and did not run. An unrun build is never reported as passing.

## Tests the connector must carry

| Test | On | Rule |
|---|---|---|
| `unique`, `not_null` | every primary key | [21, 28](../../../rules/analytics-engineering-rules.md) |
| `relationships` | every foreign key into a conformed dimension | [28](../../../rules/analytics-engineering-rules.md) |
| `accepted_values` | every column with a closed domain | [28](../../../rules/analytics-engineering-rules.md) |
| `not_null` on the org/tenant key | every adapter, if the project has one | — |

That last one is worth its own line. A connector whose org identifier is not aliased to the
project's conformance anchor builds fine, passes every other test, and then its rows vanish
from every company-scoped query. Nothing else catches it.

## Documentation

- A description that states the **grain**, not the model name
  ([rule 33](../../../rules/analytics-engineering-rules.md)).
- The connector's row added to the use-case's source contract and bus matrix, if they exist.
- Every unanswered question left as `[NEEDS INPUT]` with who can answer it.
- The **rollback path** ([rule 40](../../../rules/analytics-engineering-rules.md)). In a
  registry-driven project it is `is_<connector>_enabled: false` — no code revert, which is
  the cheapest rollback the project has. Say so explicitly rather than assuming the reader
  infers it.

## Committing

Load `git-commit-quality`. Never commit to `main` or `master`.

```bash
git switch -c feat/<ticket>-<connector>-connector
git add -A
bash .claude/commands/infra/git-standard.sh \
    "feat(<connector>): add <Display> connector to <use-case>"
```

`git-standard.sh` enforces three things and refuses otherwise: not on `main`/`master`, the
branch matches `<type>/<ticket>-<description>`, and the message is a Conventional Commit. It
wraps `git commit` only — staging is yours.

Split the work where practical: the mechanical scaffold and the hand-written column mapping
are separate changes, and reviewing them in one commit hides the second inside the first.

**Push and open a PR only when asked.** Then:

```bash
git push -u origin HEAD
```

followed by `/pr-ready` and `/review`.

## Definition of done

- [ ] Use-case exists and was read before anything was written
- [ ] Source declared with `loaded_at_field` and `freshness`
- [ ] Registry entry (if the project has a registry), key string-matching the var, the
      directory, and the filename prefix
- [ ] `is_<connector>_enabled` declared in `dbt_project.yml`, connector tag added
- [ ] One staging model per raw table, columns enumerated, no `select *` surviving
- [ ] One adapter per claimed unified concept, columns matching the others in order
- [ ] `unique`/`not_null` on every PK, `relationships` on every FK
- [ ] Repository tests green
- [ ] `dbt build --select tag:<connector>` green, **and green again unioned with an
      existing connector**
- [ ] Build still green with the connector disabled
- [ ] Rollback path stated
- [ ] Committed via `git-standard.sh` on a correctly named branch, not on `main`
