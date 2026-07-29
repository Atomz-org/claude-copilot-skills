# Unified Operating Manual

Repository name: `code-skills`

This repository combines:

- Git workflow automation and reusable scaffold operations
- Senior analytics-engineering methods for dbt Core projects
- RTK-style toolkit routing, graph state, and memory capture

## Graphify-first rule

This project uses graph-based navigation when graph outputs are present.

Rules:
- For codebase questions, run `graphify query "<question>"` when `graphify-out/graph.json` exists.
- For relationships, use `graphify path "<A>" "<B>"`.
- For focused concepts, use `graphify explain "<concept>"`.
- If `graphify-out/wiki/index.md` exists, use it for broad navigation first.
- Read `graphify-out/GRAPH_REPORT.md` only for broad architecture review or when scoped queries are insufficient.
- After meaningful code edits, run `graphify update .` to keep graph state current.

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
