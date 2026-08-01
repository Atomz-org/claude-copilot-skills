# Why this runs without an LLM

skill-map upstream has two halves. Only one is wired into this repository.

| Half | What it is | Used here |
|---|---|---|
| Deterministic scanner | Walks Markdown, parses frontmatter, resolves references, runs analyzers, emits a graph | **Yes** |
| Probabilistic layer | Queues LLM jobs (summaries, duplicate/bloat/contradiction finders, tagging) for an agent to execute | **No** |

The separation is upstream's own design, not something this repository invented:
the scanner is documented as "pure code, offline, CI-safe", and skill-map never
ships or requires a key. What this repository adds is an enforcement boundary,
so the property holds even if someone later edits the wrapper.

## The enforcement boundary

Every `sm` invocation in this repository goes through `_run_sm()` in
`scripts/skill_map_scan.py`, which rejects any verb outside an allowlist:

```python
DETERMINISTIC_VERBS = frozenset({
    "init", "scan", "check", "list", "show",
    "orphans", "export", "graph", "version", "doctor",
})

PROBABILISTIC_VERBS = frozenset({"jobs", "agent", "findings", "refresh"})
```

The rejection raises rather than warns. A guard that could be talked past would
not support the claim this file makes.

The four excluded verb families are the whole probabilistic surface:

- `jobs *` — enqueue, claim, and record LLM work (`jobs submit`, `jobs claim`).
- `agent *` — installs the `sm-process-jobs` skill that executes that queue.
- `findings *` — reads and manages the judgments those jobs produce.
- `refresh` — recomputes enrichment rows, which are LLM-derived.

`tests/test_skill_map_pack.py` pins the allowlist against that set, so adding a
probabilistic verb to the wrapper fails the suite rather than silently changing
what the repository depends on.

## What the scan still needs

Not an API key, but not nothing:

- **Node.js.** The CLI is a Node program. `scripts/skill_map_scan.py` resolves
  it as `SKILL_MAP_BIN` → `sm` on `PATH` → `npx -y @skill-map/cli@<pinned>`.
- **Network, once.** Only on the `npx` path, and only until npm's cache is
  warm. An installed `sm` or a set `SKILL_MAP_BIN` needs no network at all.

When none of the three resolve, the runner exits `3` (unavailable) instead of
failing. Callers record a `skip`. A repository check must not turn red because a
particular machine has no Node on it.

## Egress

The wrapper sets `SKILL_MAP_TELEMETRY=0` and `SM_NO_UPDATE_CHECK=1` on every
invocation, so a scan makes no analytics call and no version ping. `NO_COLOR=1`
is set for the same reason a machine-readable flag exists — ANSI escapes would
corrupt a `--json` consumer.

## What a scan leaves in the work tree

Two paths, and both are already handled — the CI activation-drift gate runs
*after* the harness scan, so anything the scan creates and nothing accounts for
is reported as drift:

- `.skill-map/` — the SQLite DB and settings. Transient, regenerated per scan,
  **gitignored**.
- `.skillmapignore` — decides which files become nodes. **Committed**, for the
  same reason the CLI version is pinned: untracked, `sm init` writes its own
  defaults per machine and the gate stops meaning the same thing in two
  checkouts. `sm init` never overwrites an existing copy.

## Scan scope and reproducibility

`.skillmapignore` excludes `graphify-out/`, which matters more than it looks.
CI runs `graphify update .` immediately before the harness scan, so that tree
exists on a runner and usually does not on a laptop; scanned, its wiki Markdown
would enter the graph and the node count would differ between the two
environments for no reason a reviewer could act on.

With it excluded, node and link counts are identical in both. One difference
survives and cannot be fixed from the ignore file: `CLAUDE.md:24` points at
`graphify-out/GRAPH_REPORT.md`, and `reference-broken` resolves against the
graph *or the disk*, so that one pointer resolves on a runner and is reported
broken on a laptop.

That is a ±1 swing in a number the gate does not read — `reference-broken` is
deliberately not one of `GATE_ANALYZERS` — so the verdict stays stable and only
the diagram's findings box moves.

## Version pinning

`PINNED_VERSION` in the wrapper fixes the CLI version. The analyzer set decides
which issues exist, so an unpinned upgrade would change the finding counts —
and therefore a CI gate's verdict — with no diff to point at. Bump it
deliberately, and expect the counts to move when you do.
