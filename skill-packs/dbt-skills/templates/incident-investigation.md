# Investigation — <short title>

**Date:** <YYYY-MM-DD> · **Investigator:** <name> · **Severity:** P1 | P2 | P3
**Status:** Investigating | Root cause found | Fixed | Won't fix

Fill this in for anything that took more than fifteen minutes or reached production.
Section 8 is the only one that changes the future.

---

## 1. Symptom

**What was observed, by whom, and when:**

**What is wrong, stated precisely:**

> e.g. "fct_orders row count dropped 40% on 2026-07-27, from ~12,000/day to ~7,200/day"
> not "orders look wrong"

| Item | Value |
|---|---|
| First observed | |
| First occurred (from the data) | |
| Detected by | test / alert / a human noticing |
| Consumers affected | |
| Is anything publicly wrong right now? | |

---

## 2. Evidence gathered

Read the artifacts before changing any code.

```bash
python scripts/run_results_analyzer.py --run-results target/run_results.json \
    --manifest target/manifest.json --top 15
python scripts/source_freshness_monitor.py --sources target/sources.json \
    --manifest target/manifest.json
cat target/compiled/<project>/models/.../<model>.sql     # what you wrote, Jinja resolved
cat target/run/<project>/models/.../<model>.sql          # what dbt actually sent
```

| Source | What it showed |
|---|---|
| `run_results.json` | |
| `sources.json` | |
| Compiled SQL | |
| `--store-failures` rows | |
| `git log` on upstream models | |
| EL job history | |
| Warehouse query history | |

---

## 3. Triage ladder

| # | Check | Result |
|---|---|---|
| 1 | `dbt parse` | |
| 2 | `dbt debug` | |
| 3 | `dbt compile --select <model>` | |
| 4 | Compiled SQL run directly in the warehouse | |
| 5 | `dbt test --select <model> --store-failures` | |
| 6 | Unit tests | |

Each rung rules out the ones below it.

---

## 4. Hypotheses

| # | Hypothesis | How it was tested | Result |
|---|---|---|---|
| 1 | | | confirmed / ruled out |
| 2 | | | |

---

## 5. Root cause

**The actual cause:**

**Category:**

- [ ] Source system change
- [ ] EL pipeline failure or change
- [ ] Upstream model change
- [ ] Incremental logic (lookback, `unique_key`, `on_schema_change`, anchoring)
- [ ] Snapshot missed changes
- [ ] Join fan-out
- [ ] SQL logic error
- [ ] Grain change that passed every test
- [ ] Warehouse/permissions/infrastructure
- [ ] dbt or package version change
- [ ] Timezone or calendar boundary
- [ ] Contested business definition (not a bug)

**Why it was not caught earlier:**

**How long it was wrong before detection:**

---

## 6. Blast radius

| Item | Value |
|---|---|
| Models affected | |
| Exposures affected | |
| Date range of bad data | |
| Were decisions made on the bad data? | |
| Do published numbers need restating? | who owns that communication |

---

## 7. Fix

**What was changed:**

**Backfill needed:**

| Item | Value |
|---|---|
| Models to rebuild | |
| Command | |
| Cost / duration | |
| Verified how | |

**Verification that the fix worked:**

| Check | Expected | Actual |
|---|---|---|
| | | |

---

## 8. The test that would have caught this

**This is the field that matters.** Every investigation ends with a new test, a new
freshness block, or a written reason why neither is possible.

| Item | Value |
|---|---|
| Test / check added | |
| Where it lives | |
| What it would have caught, and how early | |
| Severity | |

**If no test is possible, say why:**

> Legitimate reasons: the failure is in a source system we do not control (mitigation is
> a freshness block plus escalation); the correct value is a business judgment nobody had
> made yet; detection requires data we do not collect (the first fix is instrumentation).
>
> "We'll be more careful" is not a reason.

---

## 9. Follow-ups

| # | Action | Owner | Ticket | Due |
|---|---|---|---|---|
| 1 | | | | |

---

## 10. Timeline

| Time | Event |
|---|---|
| | data first became wrong |
| | detected |
| | investigation started |
| | root cause found |
| | fix deployed |
| | backfill complete |
| | consumers notified |

**Time to detect:** ___ · **Time to fix:** ___

If time-to-detect is much larger than time-to-fix, the problem is monitoring, not the bug.
