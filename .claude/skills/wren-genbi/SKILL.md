---
name: wren-genbi
description: WrenAI semantic layer over this repository's dbt use-cases — governed SQL through MDL, compiled metric views, a per-use-case MCP server, knowledge-enriched context, and GenBI dashboards. Use whenever the user asks a data question against a use-case (how many, top N, revenue by, trend), wants a use-case served through a semantic layer, wants to regenerate or validate a wren/ project, or asks to build a shareable dashboard. Triggers - "wren", "semantic layer query", "genbi", "governed sql", "metric view", "wren mcp", "wren demo".
license: Apache-2.0
metadata:
  upstream: Adapted from WrenAI's discovery stub (external/WrenAI/skills/wren/SKILL.md, Apache-2.0)
---

# WrenAI over dbt use-cases

WrenAI is a semantic SQL layer: YAML context (`models/`, `relationships.yml`, `views/`,
`knowledge/`) compiles to an MDL manifest that plans and governs SQL against 20+
datasources. In this repository it is the **serving tier of a use-case**: each use-case can
carry a generated `wren/` project beside its `ontology/` artifacts.

This is a discovery stub, by upstream design: the real workflow guides ship **inside the
`wren` CLI** and are always version-matched to it. Never copy guide content into this
repository — fetch it:

```bash
wren skills list                 # available guides
wren skills get usage            # day-to-day querying workflow
wren skills get onboarding       # connect a new database
wren skills get enrich-context   # add business context
wren skills get genbi            # build & deploy a dashboard app
wren docs connection-info <ds>   # exact connection fields per datasource
```

The CLI resolves from `.venv-wren/bin/wren` (create: `python3 -m venv .venv-wren &&
.venv-wren/bin/pip install -r requirements.txt`). Source is pinned at `external/WrenAI`.

## Repository integration — read before touching wren/

- **`wren/` is generated.** `python3 scripts/use_case_sync.py --use-case <slug> --stage wren`
  runs WrenAI's native dbt importer and then enriches it from this repository's artifacts:
  ontology concepts and column contracts → `knowledge/rules/`, adapter drift →
  `knowledge/caveats/`, MetricFlow metrics and saved queries → `views/` (one MDL view per metric —
  `SELECT * FROM <metric>` is the governed definition) plus
  `knowledge/rules/semantic-metrics.md`. Regenerate; never hand-edit a generated file. Hand-authored knowledge goes in
  **new** files under `knowledge/` — both generators leave unknown files alone.
- **Inputs**: a parsed manifest plus `catalog.json` (`dbt docs generate` against the local
  DuckDB target). Missing inputs make the stage skip with the remedy named.
- **Follow [wren-rules.md](../../rules/wren-rules.md)** for the binding rules (ownership,
  gates, egress).

## Day-to-day

```bash
wren dry-plan --sql '...'        # plan through MDL, no database needed — the cheap gate
wren query --sql '...'           # governed execution
wren query --sql 'select * from <metric>'   # the compiled metric view IS the metric
wren context show / instructions # what the agent-facing context contains
wren context validate && wren context build   # after any regeneration
```

For the worked end-to-end demo (dbt build → import+enrich → governed query, all local
DuckDB): `./skill-packs/wren-skills/demo/run_wren_demo.sh` — architecture and rationale in
`docs/WRENAI_INTEGRATION.md` at the repository root.
