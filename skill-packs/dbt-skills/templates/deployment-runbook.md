# Deployment Runbook — <change name>

**Author:** <name> · **Date:** <YYYY-MM-DD> · **PR:** <link>
**Risk:** low | medium | high

---

## 1. What changes

| Item | Value |
|---|---|
| Models added | |
| Models modified | |
| Models removed | |
| Sources added/changed | |
| Contracts / versions affected | |
| Semantic models or metrics affected | |

**Downstream impact** (from `model_dependency_analyzer.py --model <m> --direction down`):

| Downstream node | Type | Owner | Notified? |
|---|---|---|---|
| | | | |

---

## 2. Pre-deploy verification

- [ ] `dbt build --select state:modified+ --defer --state prod/` green in CI
- [ ] `dbt_project_auditor.py --strict` clean
- [ ] `contract_breaking_change_detector.py --strict` clean, or every break versioned
- [ ] `test_coverage_reporter.py --strict` clean
- [ ] `semantic_layer_validator.py --strict` clean (if metrics changed)
- [ ] Source freshness green for every source the change depends on

**Baseline captured before deploy:**

| Model | Row count | `sum()` of key numeric column | Max timestamp | Build time |
|---|---|---|---|---|
| | | | | |

---

## 3. Deploy

```bash
# Order matters: sources → snapshots → models. A snapshot missed between runs is
# unrecoverable, so it runs before anything can fail the build.
dbt deps
dbt source freshness --target prod
python scripts/source_freshness_monitor.py --sources target/sources.json \
    --manifest target/manifest.json --strict          # gates the build

dbt snapshot --target prod
dbt build --select <selector> --target prod
```

| Step | Command | Expected duration | Owner |
|---|---|---|---|
| 1 | | | |
| 2 | | | |

**Backfill required?**

| Item | Value |
|---|---|
| Models needing `--full-refresh` | |
| Estimated cost | |
| Estimated duration | |
| Window during which the table is inconsistent | |
| Consumers affected during the window | |

---

## 4. Post-deploy verification

Do not close the ticket on a green build.

- [ ] **Row count** vs baseline — a 10x or 0.1x change is a defect until explained
- [ ] **`sum()` of every material numeric column** vs baseline
- [ ] **Freshness** — did `max(<timestamp>)` actually advance?
- [ ] **The consumer** — open the dashboard. Green tests and a broken chart happen
- [ ] **Build time** vs baseline

```bash
python scripts/run_results_analyzer.py --run-results target/run_results.json \
    --manifest target/manifest.json --compare prod/run_results.json --slower-than 1.5
```

| Check | Expected | Actual | Pass? |
|---|---|---|---|
| Row count | | | |
| Revenue total | | | |
| Max timestamp | | | |
| Build time | | | |

---

## 5. Rollback

**Trigger conditions** — decide these before deploying, not during the incident:

| Condition | Action |
|---|---|
| Test failure at `error` severity | rollback |
| Row count off by more than `<x%>` | rollback |
| Consumer reports wrong numbers | rollback |
| Build time up more than `<x%>` | investigate, do not rollback |

**Procedure:**

```bash
git revert <sha>
dbt build --select <selector> --target prod          # add --full-refresh for incrementals
```

| Item | Value |
|---|---|
| Rollback duration | |
| Rollback cost (full-refresh, if any) | |
| Data loss risk | |
| **Not revertible** (snapshots, dropped columns) | |

For a high-risk mart, prefer building alongside — `{{ config(alias='fct_orders_v2') }}`,
verify with `audit_helper.compare_relations`, then swap the alias in a one-line PR.
Rollback is then the reverse one-liner.

---

## 6. Communication

| Audience | Message | When | Sent? |
|---|---|---|---|
| Consumer owners | | before deploy | |
| On-call | | at deploy | |
| Stakeholders (if numbers restate) | | | |

**If published numbers change**, someone owns that communication. Name them here.

---

## 7. Artifacts

- [ ] `manifest.json`, `run_results.json`, `sources.json`, `catalog.json` uploaded — **including on failure**
- [ ] Dated copy of `run_results.json` archived for regression comparison

---

## 8. Outcome

| Item | Value |
|---|---|
| Deployed at | |
| Verification result | |
| Rolled back? | why |
| Surprises | |
| Follow-up tickets | |
