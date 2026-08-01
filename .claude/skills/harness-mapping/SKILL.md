---
name: harness-mapping
description: "Map this repository's own AI harness — every skill, command, and agent as one graph, with name collisions, broken references, reserved-name shadowing, and token weight. Deterministic and offline; no LLM, no API key. Use when auditing the harness, before adding a skill or command, when two entries answer to the same name, when a /command does not fire, or when asked what the harness contains or what is safe to delete."
---

# Harness mapping (skill-map)

Backs the `/skill-map` command. The skill is named `harness-mapping` rather than
`skill-map` because a skill and a command that share a name shadow each other,
and the command loses — `tests/test_new_connector.py` pins that rule.

A harness grows by accumulation. This repository already carries ~37 skills, ~37
commands, and ~10 agents across two mirrored trees, and nothing in the normal
workflow shows you that whole surface at once. skill-map scans it and returns a
graph: what exists, what each file weighs in tokens, who references whom, which
names collide, and which references are dead.

**The scanner is pure code.** It parses Markdown and frontmatter and resolves
references. It does not call a model, does not read an API key, and runs
offline. skill-map's upstream project also ships a probabilistic layer that
queues LLM jobs — this repository does not use it, and
`scripts/skill_map_scan.py` cannot reach it. See
[references/determinism.md](references/determinism.md) for how that is enforced.

## When to reach for this

- Before adding a skill or command — check the name is not already taken.
- A `/command` does not fire, or the wrong one does. Usually a collision or a
  name reserved by the Claude Code runtime.
- After a pack edit, to confirm the pack and its activated mirror still agree.
- "What is in this harness?" / "What can we delete?" / "What does this cost?"

For questions about *application* code, use `graphify` instead — see the
Graphify-first rule in `CLAUDE.md`. skill-map maps the harness; graphify maps
the codebase. They are different graphs and neither substitutes for the other.

## Run it

The wrapper is the supported entry point. It pins the CLI version, forces the
deterministic verb set, and degrades to "unavailable" rather than failing when
Node is absent:

```bash
python scripts/skill_map_scan.py --summary                   # counts + collisions
python scripts/skill_map_scan.py --json /tmp/scan.json       # full ScanResult
python scripts/skill_map_scan.py --check --max-errors 0      # CI gate form
```

Exit codes: `0` clean, `1` over the structural-error budget (`--check` only),
`2` runner defect, `3` no `sm` CLI available on this machine.

Reading a summary is usually enough. Pull the full `--json` only when you need
per-node detail, and query it rather than pasting it — a ScanResult for this
repository is several hundred KiB.

The upstream CLI can also be driven directly for interactive work
(`sm check`, `sm show <node>`, `sm list`). Those verbs and their output shapes
are in [references/verbs.md](references/verbs.md).

## Reading the findings

Not every issue is a defect. This repository legitimately keeps two copies of
each pack asset — the pack under `skill-packs/<pack>/` and the activated mirror
under `.claude/` — so **every finding appears twice**, once per tree. Halve the
counts before reacting, and fix the pack copy, never the mirror.

The analyzers, what each one actually means here, and which are worth acting on
are in [references/findings.md](references/findings.md).

Priority order when triaging:

1. `name-collision` — two entries answer to one name. Dispatch is undefined.
2. `frontmatter-parse-error` — the frontmatter is not valid YAML. A strict
   parser drops the entry entirely, so it silently stops loading elsewhere.
3. `reference-broken` — a dead pointer. Check it is not an illustrative path
   inside prose before "fixing" it; this analyzer does not distinguish them.
4. `name-reserved` — shadowed by a Claude Code built-in. The built-in wins.
5. `frontmatter-invalid` / `link-self-loop` — worth a look, rarely urgent.

## Working rule

Treat a new collision or a new frontmatter parse error as a defect in the change
that introduced it. Both are invisible at runtime — the harness just quietly
loads something other than what you meant — which is exactly the class of
problem this scan exists to surface.
