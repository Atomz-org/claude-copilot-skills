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

## Version pinning

`PINNED_VERSION` in the wrapper fixes the CLI version. The analyzer set decides
which issues exist, so an unpinned upgrade would change the finding counts —
and therefore a CI gate's verdict — with no diff to point at. Bump it
deliberately, and expect the counts to move when you do.
