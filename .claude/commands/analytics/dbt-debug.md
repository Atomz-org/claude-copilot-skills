---
description: Triage a failed dbt run, test, or compile from the artifacts
argument-hint: <the error message, the failing node, or "the nightly job failed">
---

Diagnose: **$ARGUMENTS**

Load `troubleshooting-dbt`.

---

## 1. Evidence before hypotheses

Never re-run to see if it passes. It sometimes does, which teaches nothing and hides an
intermittent bug.

```bash
dbt --version
python scripts/run_results_analyzer.py --run-results target/run_results.json \
    --manifest target/manifest.json --top 15
```

`run_results.json` has the status, the timing, the node id, the adapter response, and the
error text — in structured form. Read it, not the scrollback.

## 2. Triage ladder — top to bottom

Each rung rules out the ones below it. Skipping is how an afternoon disappears.

| # | Check | Command | If it fails |
|---|---|---|---|
| 1 | Does it parse? | `dbt parse` | YAML/Jinja syntax. Nothing downstream is real |
| 2 | Connection? | `dbt debug` | Profile, credentials, role, network |
| 3 | Does it compile? | `dbt compile --select <model>` | Jinja, missing `ref`, missing macro |
| 4 | Does the SQL run? | paste `target/compiled/...` into the warehouse | It is a SQL/warehouse problem, not dbt |
| 5 | Do the tests pass? | `dbt test --select <model> --store-failures` | Data quality — read the failure rows |
| 6 | Is the logic right? | unit tests | Go to `dbt-unit-testing` |

## 3. Read the right file

```bash
cat target/compiled/<project>/models/.../<model>.sql   # your SQL, Jinja resolved
cat target/run/<project>/models/.../<model>.sql        # what dbt actually SENT (incl. DDL)
```

Debugging Jinja by reading the model file does not work — read `target/compiled/`.
Incremental merge bugs are visible only in `target/run/`.

To inspect a value mid-compile: `{{ log("value: " ~ x, info=true) }}`.

## 4. Match the failure class

| Class | First check |
|---|---|
| Compile / parse | spelling in `ref`/`source`; `dbt deps`; `enabled: false`; unbalanced Jinja |
| `relation does not exist` | upstream not built in this target, or a stale `--defer` manifest |
| Permission denied | role grants — `dbt debug` confirms the connection, not object-level access |
| Test failure | `--store-failures`, then query the rows. **Do not weaken the test first** |
| Numbers wrong, nothing errored | fan-out, or a grain change. Count each CTE in isolation |
| Incremental divergence | lookback too short, `unique_key` missing, filter anchored to `current_date` |
| Freshness | is `loaded_at_field` a load timestamp or a source `updated_at`? |
| Slow | `run_results_analyzer.py --compare` — is it one node or all of them? |
| Suddenly failing after months | an upstream or source-system change, not decay. Check `git log` upstream and the EL job history |

## 5. The incremental invariant

If the numbers are wrong on an incremental model, check this before anything else:

> `dbt build --select <model> --full-refresh` must reproduce the incremental result.

If it does not, the model is corrupt and every number from it is suspect. Common causes:
the lookback is shorter than the actual arrival lag; the filter is anchored to
`current_date` instead of `max()` in `{{ this }}`; `unique_key` is missing or not actually
unique.

## 6. One hypothesis, one change

Form one hypothesis, test it, change one thing, re-run. `--full-refresh` is not a first
response — it masks incremental logic bugs and costs real money.

## 7. Know when to stop and escalate

Escalate rather than guessing when:

- the fix requires a **business decision** — which of two disagreeing sources is right, or
  whether history should be restated;
- the failure is in the **source system or EL job** — modeling around bad source data hides
  the bug and makes it permanent;
- a fix would **restate published numbers** — someone owns that communication;
- the data is **wrong but plausible** and you cannot determine what it should be. Say so
  explicitly rather than shipping a guess.

## 8. Record it

For anything over fifteen minutes or that reached production, fill
[templates/incident-investigation.md](../../templates/incident-investigation.md).

Section 8 — **the test that would have caught this** — is the only field that changes the
future. Every investigation ends with a new test, a new freshness block, or a written
reason why neither is possible. "We'll be more careful" is not a reason.

---

## Rules that bind here

[Rule 41](../rules/analytics-engineering-rules.md): failures are diagnosed from artifacts,
not by re-running blindly. [Rule 23](../rules/analytics-engineering-rules.md): an
incremental model whose full refresh differs from its incremental result is corrupt.

## Output

1. **Root cause**, stated precisely — not "something upstream changed".
2. **The evidence** that established it, with the file or query.
3. **Blast radius** — which models, which exposures, which date range, whether published
   numbers are wrong.
4. **The fix**, and the backfill if one is needed with its cost.
5. **The test that would have caught it.**
