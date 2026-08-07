# CodeRabbit findings as tracked work

A CodeRabbit review comment is the right place to **discuss** a finding and the wrong place
to **track** one. It is invisible from a board, it disappears when the pull request closes,
and nothing counts it. This bridge moves the findings worth tracking into GitHub issues on
a project, and closes them again when the thread they came from is resolved.

| | |
|---|---|
| Script | [scripts/coderabbit_to_issues.py](../scripts/coderabbit_to_issues.py) |
| Workflow | [.github/workflows/coderabbit-issues.yml](../.github/workflows/coderabbit-issues.yml) |
| Tests | [tests/test_coderabbit_to_issues.py](../tests/test_coderabbit_to_issues.py), [tests/test_workflow_triggers.py](../tests/test_workflow_triggers.py) |
| Summary in the operating manual | [CLAUDE.md](../CLAUDE.md) |

---

## What it does

Two directions, one script.

```
CodeRabbit review comment                          GitHub issue
  _🔒 Security & Privacy_ | _🟠 Major_ | …    ──▶   labelled `coderabbit`, `severity: major`
  **Bind the published port to loopback.**          added to ProjectV2 #1
                                                    body carries the comment id as a marker

  thread marked resolved                     ──▶   issue closed as `completed`
  pull request closed unmerged               ──▶   issue closed as `not planned`
```

Nothing is written without `--write`. The default prints exactly what it would do and exits
`0`, because the target is a real tracker rather than a generated artifact.

---

## Measured before it was built

Run against the repository's nine open pull requests:

| Severity | Findings |
|---|---|
| 🔴 Critical | 5 |
| 🟠 Major | 53 |
| 🟡 Minor | 33 |
| **Total** | **91** |
| Unreadable | **0** |

Distribution is lopsided — one pull request carries 40 of the 91:

```
#78  ████████████████████████████████████████  40
#86  ███████████████████                       19
#82  █████████████████                         17
#84  ███████████                               11
#83  ████                                       4
```

**Backfilling every open pull request therefore opens 91 issues at once.** The severity
floor is a workflow input, so `--min-severity major` files 58 and `critical` files 5.

---

## Setup

### 1. The project token — the one prerequisite

`GITHUB_TOKEN` **cannot** write to an organisation ProjectV2. The issue half works without
it; the project half does not.

```bash
gh secret set CODERABBIT_PROJECT_TOKEN --repo <owner>/<repo>
```

The token needs `project` scope (classic PAT) or organisation project write (fine-grained).

Without the secret the run still creates every issue and reports:

```
note: no $CODERABBIT_PROJECT_TOKEN — issues created, project #1 not touched
      (GITHUB_TOKEN cannot write an org ProjectV2)
```

That is deliberate. A gate that goes red because an optional credential is absent gets
switched off within a week, taking the real failures with it.

### 2. Labels

Created on first `--write` run: `coderabbit`, plus `severity: critical|major|minor|trivial`.
`gh label create` is not idempotent, so an "already exists" failure is swallowed — that is
the only reason it fails here.

### 3. Nothing else

The workflow needs no checkout secrets, no App, and no CodeRabbit configuration. It reads
what CodeRabbit has already posted.

---

## Usage

```bash
# Dry run — what would be filed for one pull request
python3 scripts/coderabbit_to_issues.py --repo <owner>/<repo> --pr 84

# File them, and add each to ProjectV2 #1
python3 scripts/coderabbit_to_issues.py --repo <owner>/<repo> --pr 84 --write --project 1

# Every open pull request
python3 scripts/coderabbit_to_issues.py --repo <owner>/<repo> --all-open --write --project 1

# Major and worse only
python3 scripts/coderabbit_to_issues.py --repo <owner>/<repo> --all-open --min-severity major

# Close whatever has since been resolved
python3 scripts/coderabbit_to_issues.py --repo <owner>/<repo> --all-open --reconcile --write

# Machine-readable
python3 scripts/coderabbit_to_issues.py --repo <owner>/<repo> --pr 84 --format json
```

Start with one pull request. `--all-open --write` is the 91-issue command.

---

## What a filed issue looks like

**Title** leads with the file, because a board shows titles and nothing else:

```
podman-compose.yml: Bind the published port to loopback
```

**Body** carries the severity, the category, a link back to the thread, CodeRabbit's own
remediation prompt, and the marker the reconciler keys on:

```markdown
**Major** · 🔒 Security & Privacy · ⚡ Quick win

Found by CodeRabbit on #84, in `skill-packs/lightdash-skills/deploy/podman-compose.yml:52`.

> Bind the published port to loopback.

[Open the review thread](https://github.com/…/pull/84#discussion_r3732681339)

<details><summary>CodeRabbit's remediation prompt</summary>
…
</details>

---
*Filed by `scripts/coderabbit_to_issues.py`. It closes automatically when the review
thread is resolved — resolve the thread, do not close this by hand, or the reconciler
will have nothing to key on.*

<!-- coderabbit-comment-id: 3732681339 -->
```

---

## The trigger that does not exist

**Resolving a review thread emits no signal a workflow can see.**

`pull_request_review_thread` (activity types `resolved` / `unresolved`) is a real GitHub
**webhook** event. It is **not** a GitHub Actions workflow trigger. It is absent from
GitHub's own workflow schema, whose `on:` list carries 35 keys including every recent
addition — `merge_group`, `discussion`, `branch_protection_rule`, `registry_package` — so
the absence is real rather than schema staleness.

This matters more than "the fast path is unavailable":

> An unknown `on:` key does not merely fail to fire the job it was added for. GitHub stops
> loading the **file**, so every other trigger in it dies too.

The first draft of the workflow listed it directly above the `schedule:` that is the only
thing which closes anything. Shipping it would have produced a workflow that looked
installed and did nothing — and a scheduled sweep that never ran looks exactly like a
scheduled sweep with nothing to do.

So there is no push path. The sweep is the mechanism, GraphQL `isResolved` is the source of
truth, and the cost is **latency, never a missed close**.

[tests/test_workflow_triggers.py](../tests/test_workflow_triggers.py) pins this for every
workflow in the repository, and one test fails deliberately if GitHub ever promotes the
event, so the push path can be added at that point rather than rediscovered.

---

## Triggers actually used

```yaml
on:
  pull_request_review:      # CodeRabbit submits a review -> file its findings
    types: [submitted]
  pull_request:             # closed unmerged -> close its issues as `not planned`
    types: [closed]
  schedule:                 # the only way a resolved thread is ever noticed
    - cron: "*/15 * * * *"
  workflow_dispatch:        # dry run by default; set `write: true` to act
```

Cron on Actions is best-effort and slips under load — treat 15 minutes as a floor, not a
guarantee.

The `file` job runs only when the review author is CodeRabbit. The `reconcile` job runs on
everything except a review submission.

---

## Four rules that decide whether the output is trustworthy

### 1. The mapping is rebuilt by listing the label, never by searching

Every issue body carries `<!-- coderabbit-comment-id: N -->`. Recovering the mapping uses
`gh issue list --label coderabbit --state all`, then parses bodies.

GitHub's search index lags writes by up to a minute, and CodeRabbit posts a **whole review
at once**. A search-backed lookup therefore duplicates the issues it was added to prevent —
intermittently, under exactly the load it will meet in practice.

The workflow is also `concurrency`-serialised repository-wide. Two runs racing would each
read "no issue exists yet" and both create one — the same duplicate arriving by a route the
marker lookup cannot see.

### 2. A finding whose title cannot be read is refused, not named after its file

A path reads like a title and is not one. The run reports it under `unreadable` instead.
Measured: 0 of 91.

### 3. An unavailable project is not a failure

The rule the rest of this repository runs on. Missing token → issues still created, project
step reported as skipped.

### 4. Closing by hand breaks the loop

The reconciler keys on the thread's `isResolved`. An issue closed manually is simply gone
from the open set, and the thread stays open forever with nothing pointing at it. The issue
body says so, in the artifact rather than in a runbook.

---

## Two parsing rules that were wrong first

Both were caught against the real 91-comment corpus, not by inspection.

### A title is not a whole line

CodeRabbit's usual shape puts the title on its own line:

```
_🗄️ Data Integrity & Integration_ | _🟠 Major_ | _⚡ Quick win_

**Use one executable path for the selected use case.**
```

But two of the 91 run the title into its first sentence:

```
**Prefix semantic-model and metric IDs by entity type.** When both share a YAML file…
```

Matching `^\*\*(.+?)\*\*$` dropped exactly those two — and they were also the two that hide
behind a collapsed `<details>` block, so the fallback would have been a bare file path.
Anchored at line start only: **26/28 → 91/91**.

### A `**` inside a fenced block is not a title

CodeRabbit's analysis sections carry whole shell scripts, one of which contained
`rg -n '**…**'`. Fenced blocks are skipped before the title is looked for.

---

## What is deliberately not filed

- **A comment with no severity header.** CodeRabbit also posts walkthroughs, summaries and
  nitpick digests. Only review comments carrying the header become issues.
- **A reply** (`in_reply_to_id` set). Somebody is discussing a thread that already has an
  issue.
- **Anything below `--min-severity`**, which defaults to `minor` — so critical, major and
  minor are filed, trivial is not.

---

## Operations

### An issue was filed for something that is not real

Resolve the CodeRabbit thread. The next sweep closes the issue as `completed` and comments
on it saying which pull request it came from.

### The issue did not close

1. Confirm the thread is actually resolved, not merely outdated. Only `isResolved` counts.
2. Run the reconciler by hand: `--reconcile` without `--write` prints what it would close.
3. Check the sweep is running at all — `test_the_coderabbit_bridge_keeps_a_schedule` guards
   the schedule's existence, not its execution.

### Duplicates appeared

That should be structurally impossible; if it happens, the marker did not round-trip.
`test_the_marker_round_trips_through_the_rendered_body` is the pin — start there.

### Turning the volume down

`--min-severity major` on the workflow input. The floor is read per-run, so lowering it
later files the minors that were skipped, without re-filing anything already tracked.

---

## Relationship to the existing auto-close

[.github/workflows/pr-issue-auto-close.yml](../.github/workflows/pr-issue-auto-close.yml)
closes issues **referenced in a merged pull request's body**. This bridge closes issues
**it filed itself**, keyed on thread resolution. Different scope, no overlap, both run on
`pull_request: closed`.

---

## Tests

24 in total. Every test on the parsing and rendering half is pure, because that is where
being wrong is silent: a GitHub call that fails is loud, but a header regex that quietly
stops matching files nothing and reports success.

| File | Covers |
|---|---|
| `test_coderabbit_to_issues.py` | header, severity floor, title derivation, marker round-trip, body content, and a live check against a real pull request (skipped without an authenticated `gh`) |
| `test_workflow_triggers.py` | every workflow's `on:` keys against GitHub's schema, with a pinned fallback for offline runs |

The trigger check was verified discriminating by re-introducing
`pull_request_review_thread` and confirming it fails.

---

## Provenance

Built 2026-08-07 against `Atomz-org/claude-copilot-skills`, nine open pull requests,
91 CodeRabbit findings. Commit `0731d87`. Full suite at that commit: 1824 passed, 1 xfailed.
