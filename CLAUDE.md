# Unified Operating Manual

Repository name: `code-skills`

This repository combines:

- Git workflow automation and reusable scaffold operations
- Senior analytics-engineering methods for dbt Core projects
- RTK-style toolkit routing, graph state, and memory capture

## Graphify-first rule

**This section is the single source of truth for graph navigation in this repository.**
Any other copy — a user-level protocol file, a source manual under `docs/source-manuals/` —
is superseded by it. State the rule here or not at all.

This project uses graph-based navigation when graph outputs are present.

Rules:
- For codebase questions, run `graphify query "<question>"` when `graphify-out/graph.json` exists.
- For relationships, use `graphify path "<A>" "<B>"`.
- For focused concepts, use `graphify explain "<concept>"`.
- If `graphify-out/wiki/index.md` exists, use it for broad navigation first.
- Read `graphify-out/GRAPH_REPORT.md` only for broad architecture review or when scoped queries are insufficient.
- After meaningful code edits, run `graphify update .` to keep graph state current.

CLI behavior, verified against the installed graphify:
- Traversal is fixed at BFS depth=2. `--depth` is accepted and **silently ignored** — do not
  rely on it to narrow a query.
- `--budget N` is the working lever. Raise it when output reports `TRUNCATED`, or narrow the
  question instead.

### TOON context pipeline

Graph output that is carried forward into LLM context is serialized as TOON
(Token-Oriented Object Notation, https://github.com/toon-format/spec), which declares
fields once and streams uniform rows instead of repeating keys per record:

```bash
# build the serializer once per clone (plain rustc -O, no cargo)
./scripts/build_toon_rs.sh

graphify query "<question>" --budget 800 | rust/toon/bin/graph_to_toon      # text → TOON
rust/toon/bin/graph_to_toon --graph graphify-out/graph.json --community "<x>"  # graph.json → TOON
... | rust/toon/bin/graph_to_toon --decode                                  # TOON → JSON for machines
```

The serializer is `rust/toon/graph_to_toon.rs`; its full functionality contract lives as
comments in that file, and `tests/test_toon_serializer.py` pins the behavior at the CLI
level (`tests/conftest.py` builds the binary on demand where `rustc` exists). TypeScript
call sites route through `src/ai-core/toon-serializer.ts` (`GraphManager.snapshotToToon()`).

### Enforcement

Enforcement is automatic, not manual — `.claude/settings.json` registers all of it; do not
add duplicate mechanisms:

- `graphify hook-guard` (`PreToolUse` on `Bash|Grep` and `Read|Glob`) injects the
  graph-first reminder at call time.
- `scripts/hooks/toon_graphify_pipe.py` (`PreToolUse` on `Bash`) rewrites bare
  `graphify query|path|explain` commands to pipe through
  `rust/toon/bin/graph_to_toon --passthrough`, and stays silent when the binary is not
  built. Composed commands (existing pipes, redirects) are left alone; `--passthrough`
  forwards unrecognized output unchanged, so the rewrite can never break a command.
- `scripts/hooks/toon_prompt_context.sh` (`UserPromptSubmit`) asserts the pipeline once
  per prompt.

Hook behavior is pinned by `tests/test_toon_pipeline_hooks.py`.

## Harness cartography — skill-map

`graphify` maps the **code**; `skill-map` maps the **harness** — skills, commands,
and agents as one graph, with name collisions, dead references, reserved-name
shadowing, and per-node token weight. Two graphs, two purposes; neither
substitutes for the other.

```bash
python scripts/skill_map_scan.py --summary                # counts + collisions
python scripts/skill_map_scan.py --check --max-errors 1   # the CI gate form
```

Deterministic and LLM-free **by construction**, not by convention: upstream
skill-map ships a probabilistic layer that queues LLM jobs, and the allowlist in
`scripts/skill_map_scan.py` rejects all four of its verb families (`jobs`,
`agent`, `findings`, `refresh`). `tests/test_skill_map_pack.py` fails if one is
ever added. No API key; exit `3` and a recorded `skip` where Node is absent.

A scan touches two paths, both already accounted for: `.skill-map/` (transient
SQLite state) is gitignored, and `.skillmapignore` (which files become nodes) is
**committed**, so the gate means the same thing in every checkout. It excludes
`graphify-out/`, which CI builds immediately before scanning and a laptop
usually lacks.

Pack: `skill-packs/skill-map/` (skill `harness-mapping`, command `/skill-map`).
Wraps `@skill-map/cli` at a pinned version rather than vendoring the upstream
monorepo — analyzers decide which issues exist, so the pin is what keeps the
gate's verdict stable.

Two rules decide whether a reading of the output is correct:

- **Every finding is doubled.** Pack and activated mirror are both scanned. A
  finding in only one tree is drift, and a different problem.
- **Fix the pack, never the mirror.**

Accepted, do not re-report: the `senior-analytics-engineer` alias collision,
`/review` shadowed by the Claude Code built-in, and agent `tools`-as-string
warnings. Details in the pack's `references/findings.md`.

## Agent and command topology

Canonical dbt skill entrypoint: `dbt-skill` (compatibility alias: `senior-analytics-engineer`).

- Agents: `.claude/agents/`
	- Meta: `repo-maintainer`, `skill-author`, `submodule-integrator`
	- Analytics: `senior-analytics-engineer`, `data-modeler`, `dbt-model-designer`, `data-contract-owner`, `analytics-quality-guardian`, `semantic-layer-architect`, `dbt-troubleshooter`
- Skills: `.claude/skills/` (dbt stage-by-stage method)
- Commands: `.claude/commands/`
	- Namespaced canonical paths:
		- Infra: `.claude/commands/infra/`
		- Analytics: `.claude/commands/analytics/`
	- Backward compatibility command files remain in `.claude/commands/`

## Generated paths — edit the pack, not the mirror

`scripts/activate_skill_stack.sh` materialises the active pack into the paths agents load.
These roots are **generated output**, and a direct edit is reverted on the next activation:

- `.claude/agents/`, `.claude/skills/`, `.claude/commands/`, `.claude/rules/`, `.claude/hooks/`
	- Source: `skill-packs/<pack>/.claude/`
- `references/`, `templates/`
	- Source: `skill-packs/<pack>/`

Both the pack copy and the root mirror must exist: skills and agents link to these assets
with a single relative path (`../../references/x.md`) that has to resolve in the pack *and*
after activation.

Exceptions maintained directly at repository level, because no pack owns them:
`.claude/commands/analytics/`, `.claude/commands/infra/`.

After changing any pack asset:

```bash
./scripts/activate_skill_stack.sh dbt-skills && git status --short
```

Unexpected modifications in that output mean an edit landed in a generated path.

## RTK and memory integration

- RTK registry and routes: `src/ai-core/rtk-setup.ts` and `src/ai-core/dbt-integration.ts`
- Graph state helper: `src/ai-core/graph-manager.ts`
- Memory store helper: `src/ai-core/memory-store.ts`
- File-backed memory updates: `.claude/commands/infra/update-memory.sh`
- Context sync pipeline: `scripts/sync_context.sh`

## dbt-labs translated skill pack

dbt-labs/dbt-agent-skills capabilities are translated for dbt Core and included in:

- `.claude/skills/dbt-labs-core-translation/SKILL.md`
- `.claude/skills/using-dbt-for-analytics-engineering-core/SKILL.md`
- `.claude/skills/running-dbt-commands-core/SKILL.md`
- `.claude/skills/building-dbt-semantic-layer-core/SKILL.md`
- `.claude/skills/adding-dbt-unit-test-core/SKILL.md`
- `.claude/skills/working-with-dbt-mesh-core/SKILL.md`
- `.claude/skills/troubleshooting-dbt-job-errors-core/SKILL.md`

## dbt Core non-negotiables

Reference file: `.claude/rules/analytics-engineering-rules.md`.

High-priority rules:
- No model before a use-case spec.
- Declare grain before SQL.
- Use only `source()` and `ref()`.
- Use `dbt build`, not run-then-test.
- No merge without tested keys and required unit tests.

## Working pattern

1. Frame request.
2. Model entities and grain.
3. Design dbt layers.
4. Build and test with selectors.
5. Run analyzers from `scripts/`.
6. Sync memory and graph context.

```bash
./scripts/sync_context.sh "dbt build for <selector>"
```

## AgentMemory guidance

Use AgentMemory for persistent cross-session context. Setup and operational commands are documented in `docs/INTEGRATIONS.md`.
