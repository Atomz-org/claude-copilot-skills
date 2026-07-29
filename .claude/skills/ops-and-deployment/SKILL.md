---
name: ops-and-deployment
description: Ship dbt Core to production — environment and target design, slim CI with state:modified and --defer, artifact storage and retrieval, orchestration (cron, Airflow, Dagster, GitHub Actions), scheduling and job design, alerting on failures and freshness, blue/green and rollback strategies, and post-deploy verification. Use when setting up CI/CD, when designing production jobs, when asked "how do I deploy this", "how do I set up slim CI", "how do I roll this back", or when a scheduled job needs designing or fixing.
---

# Ops and Deployment

Getting dbt into production is mostly two things: **only build what changed**, and **store
the artifacts** that make that possible.

## Environments

Three targets, in `profiles.yml`. Isolation is by database or schema, never by trust.

| Target | Database / schema | Who runs it | Purpose |
|---|---|---|---|
| `dev` | `ANALYTICS_DEV` / `dbt_<username>` | a developer's laptop | iteration; one personal schema each |
| `ci` | `ANALYTICS_CI` / `dbt_ci_pr_<number>` | CI runner | validate a PR; dropped after merge |
| `prod` | `ANALYTICS` / `marts`, `staging`, ... | the orchestrator only | the real thing |

Non-negotiables:

- **Personal dev schemas.** `dbt_priya`, not a shared `dev`. Two people building the same
  model into one schema is a class of bug that wastes days.
- **Ephemeral CI schemas**, named per PR, dropped on merge. Otherwise CI schemas accumulate
  until someone runs out of quota.
- **Nobody runs `--target prod` from a laptop.** Production runs come from the orchestrator,
  with credentials the orchestrator holds and artifacts it stores.
- **Snapshots write to a shared, non-suffixed schema** in every environment. A snapshot
  built into a dev schema captures dev-timed history that can never be merged into prod.

## Slim CI

Rebuilding the whole project on every PR gets the check disabled within a month. Build only
what changed and its children, and **defer** everything else to production.

```yaml
# .github/workflows/dbt_ci.yml
name: dbt CI
on: pull_request

jobs:
  build:
    runs-on: ubuntu-latest
    env:
      SNOWFLAKE_ACCOUNT: ${{ secrets.SNOWFLAKE_ACCOUNT }}
      SNOWFLAKE_USER:    ${{ secrets.SNOWFLAKE_CI_USER }}
      SNOWFLAKE_KEY:     ${{ secrets.SNOWFLAKE_CI_KEY }}
      DBT_CI_SCHEMA: dbt_ci_pr_${{ github.event.number }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.11'}

      - run: pip install -r requirements.txt        # dbt-core and adapter, both pinned

      # The production manifest is the whole trick. Without it there is no "what changed".
      - name: Fetch production artifacts
        run: |
          mkdir -p prod
          aws s3 cp s3://dbt-artifacts/prod/manifest.json    prod/manifest.json
          aws s3 cp s3://dbt-artifacts/prod/run_results.json prod/run_results.json || true

      - run: dbt deps

      # Structural gates: cheap, fast, no warehouse.
      - run: dbt parse
      - run: python scripts/dbt_project_auditor.py --manifest target/manifest.json --strict
      - run: python scripts/contract_breaking_change_detector.py --base prod/manifest.json --head target/manifest.json --strict
      - run: python scripts/test_coverage_reporter.py --manifest target/manifest.json --layer marts --min-coverage 0.9 --strict

      # Schema-only validation: zero data scanned, catches most breakage.
      - run: dbt build --select state:modified+ --defer --state prod/ --empty --target ci

      # Real build of the changed slice, with tests.
      - run: dbt build --select state:modified+ --defer --state prod/ --target ci --warn-error

      - name: Drop the CI schema
        if: always()
        run: dbt run-operation drop_ci_schema --args "{schema: $DBT_CI_SCHEMA}" --target ci
```

### How `--defer` works, and the mistake to avoid

With `--defer --state prod/`, any `ref()` to a model **not in the current selection**
resolves to the production relation instead of a CI one. So a PR touching one mart builds
one model and reads real production upstream data — seconds instead of an hour.

The mistake: pointing `--state` at the *current* `target/` directory. `--state` must be the
**previous** (production) manifest. Pointed at the current one, `state:modified` matches
nothing and CI silently validates nothing at all.

### `state:` methods

| Selector | Matches |
|---|---|
| `state:new` | nodes absent from the state manifest |
| `state:modified` | any change: SQL body, config, tests, descriptions, macros used |
| `state:modified.body` | only the SQL body |
| `state:modified.configs` | only config changes |
| `state:modified.contract` | contract changes — the breaking-change gate |
| `state:modified.macros` | a macro the model depends on changed |
| `state:old` | nodes present in state but not in the current project |

`state:modified` is deliberately broad — it includes description-only edits. Narrow with
`state:modified.body+` if the noise is a real problem, accepting that a config-only change
then goes unvalidated.

## Artifact storage

This is the piece teams skip, and it disables slim CI, freshness monitoring, and breaking-
change detection all at once.

```bash
# End of every production run — even on failure
aws s3 cp target/manifest.json     s3://dbt-artifacts/prod/manifest.json
aws s3 cp target/run_results.json  s3://dbt-artifacts/prod/run_results.json
aws s3 cp target/sources.json      s3://dbt-artifacts/prod/sources.json
aws s3 cp target/catalog.json      s3://dbt-artifacts/prod/catalog.json

# Keep a dated copy for regression comparison
aws s3 cp target/run_results.json "s3://dbt-artifacts/history/$(date +%F)/run_results.json"
```

| Artifact | Enables |
|---|---|
| `manifest.json` | `state:modified`, `--defer`, breaking-change detection, every script here |
| `run_results.json` | performance regression comparison, `dbt retry`, failure alerting |
| `sources.json` | freshness monitoring and SLA reporting |
| `catalog.json` | the docs site, real column types for contracts |

Upload on failure too — a failed run's `run_results.json` is exactly what you need to
diagnose it.

## Production job design

Split into jobs by cadence and failure blast radius, not one monolith.

```bash
# 1. Freshness gate — running the build on stale sources wastes money and publishes stale numbers
dbt source freshness --target prod
python scripts/source_freshness_monitor.py --sources target/sources.json \
    --manifest target/manifest.json --strict     # exit 1 blocks the build

# 2. Snapshots — often more frequent than marts; a change between runs is invisible forever
dbt snapshot --target prod

# 3. The build
dbt build --target prod --threads 12 --exclude tag:nightly

# 4. Docs and artifacts
dbt docs generate --target prod
<upload target/*.json>

# 5. Semantic layer exports (if used)
dbt sl export --saved-query weekly_revenue_by_region --target prod
```

| Job | Cadence | Notes |
|---|---|---|
| Source freshness | before every build | gates the build |
| Snapshots | hourly or more often | independent of the marts; missed changes are unrecoverable |
| Core build | hourly to daily, per the consumer's need | `--exclude tag:nightly` |
| Nightly reconciliation | daily | `--select tag:nightly` — expensive tests |
| Full refresh | weekly or monthly | proves the incremental invariant still holds |
| `docs generate` | daily | after the build |

Design each job to be **idempotent and safely retryable**. `dbt retry` re-runs only what
failed, which turns a partial failure into a two-minute recovery.

## Orchestration

| Tool | Fit |
|---|---|
| **cron + a shell script** | one project, one cadence, few dependencies. Genuinely fine — do not over-engineer |
| **GitHub Actions (schedule)** | small teams already on GitHub; watch the job timeout |
| **Airflow** | dependencies on non-dbt tasks; `astronomer-cosmos` renders each dbt model as an Airflow task, giving per-model retry and observability |
| **Dagster** | asset-oriented; `dagster-dbt` maps models to assets with lineage across dbt and non-dbt work |
| **Prefect / Kestra / Argo** | similar; pick what the platform team already runs |

Two patterns, whatever the tool:

- **One task for the whole `dbt build`** — simple, but retries the whole thing and gives
  coarse observability.
- **One task per model** (Cosmos, dagster-dbt) — granular retry and per-model alerting, at
  the cost of scheduler overhead and a more complex setup.

Start with one task. Move to per-model when a failure in one model genuinely should not
block unrelated branches of the DAG.

## Alerting

Alert on the things that mean something, and route them to someone who can act.

| Condition | Severity | Route |
|---|---|---|
| Production build failed | page | on-call |
| A test with `severity: error` failed | page | model owner (from the `group`) |
| Source freshness `error_after` breached | page | the EL/platform team, not analytics |
| Source freshness `warn_after` breached | ticket | EL team |
| A test at `severity: warn` failed | ticket | model owner |
| Build time up >50% run over run | ticket | analytics engineering |
| A contracted model's shape changed | block the PR | the author |

```bash
# Parse run_results into an alert payload
python scripts/run_results_analyzer.py --run-results target/run_results.json \
    --manifest target/manifest.json --json > /tmp/results.json
```

Route by model **owner group**, not to one shared channel. A channel where every alert lands
is a channel nobody reads.

## Rollback

Every deployment states its rollback path **before** it ships.

| Change | Rollback |
|---|---|
| A `view` model | revert the commit, rebuild — seconds |
| A `table` model | revert the commit, rebuild — the cost is one full build of that model |
| An `incremental` model | revert **and** `--full-refresh`. State the refresh cost and duration in the PR |
| A schema/contract change | revert plus coordinate consumers; this is why versions exist |
| A snapshot config change | **not revertible.** Restore from the backup taken beforehand |
| A dropped column consumers use | revert, rebuild, and notify — assume someone's dashboard broke |

For a high-risk mart, build alongside rather than in place:

```sql
{{ config(alias='fct_orders_v2') }}
```

Build `fct_orders_v2`, verify it with `audit_helper.compare_relations` against `fct_orders`,
then swap the alias in a one-line PR. Rollback is the reverse one-liner.

## Post-deploy verification

Do not close the ticket on a green build:

1. **Row count** vs the previous run — a 10x or 0.1x change is a defect until explained.
2. **Sum of every material numeric column** vs the previous run.
3. **Freshness** — did `max(<timestamp>)` actually advance?
4. **The consumer** — open the dashboard. Green tests and a broken chart happen.
5. **Build time** — compare against the previous run; a large jump is a regression to
   investigate now, not next quarter.

```bash
python scripts/run_results_analyzer.py --run-results target/run_results.json \
    --compare prod/run_results.json --slower-than 1.5
```

## Deployment checklist

- [ ] `dbt build --select state:modified+` passes in CI
- [ ] The breaking-change detector is clean, or every break is versioned
- [ ] The audit and coverage gates pass
- [ ] The rollback path is written in the PR description
- [ ] Incremental models: the full-refresh cost is stated
- [ ] New sources have freshness blocks
- [ ] New marts have an exposure and a named owner
- [ ] Alerting routes to a group that exists
- [ ] Downstream consumers of any changed model have been notified
- [ ] Post-deploy verification is scheduled, not assumed

## Anti-patterns

- CI that rebuilds the whole project. It gets disabled.
- No stored production artifacts — slim CI, freshness monitoring, and impact detection all
  become impossible at once.
- `--state` pointing at the current `target/`, so `state:modified` silently matches nothing.
- Running production from a laptop.
- One shared dev schema.
- A monolithic hourly job that runs snapshots, sources, and marts together, where any
  failure blocks everything.
- Alerting every test failure to one channel until nobody reads it.
- A deploy with no stated rollback.
- Never running a full refresh, so nobody notices the incremental invariant broke months ago.

Reference: [references/state_and_ci.md](../../../references/state_and_ci.md).
