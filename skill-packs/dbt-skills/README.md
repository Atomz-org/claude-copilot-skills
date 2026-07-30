# dbt-skills (domain pack)

This pack contains dbt and analytics-engineering specific assets.

Contents:

- `.claude/skills/`: dbt skills, translated dbt-labs Core skills, and analytics methods
- `.claude/commands/`: analytics command set (`dbt-*`, `data-model`, `new-use-case`, `sync-context`)
- `.claude/agents/`: analytics domain agents
- `.claude/rules/analytics-engineering-rules.md`: dbt non-negotiables
- `.claude-plugin/plugin.json`: plugin-style manifest for harness portability metadata

This pack is designed to be layered on top of `skill-packs/github-skills`.

Canonical skill entrypoint:

- `dbt-skill` in `.claude/skills/dbt-skill/SKILL.md`
- Compatibility alias: `.claude/skills/senior-analytics-engineer/SKILL.md`

Use-case artifacts for dbt agents belong under:

- `skill-packs/dbt-skills/use-cases/<slug>/`

Current use cases:

- `skill-packs/dbt-skills/use-cases/example-order-revenue-mart/`
- `skill-packs/dbt-skills/use-cases/enhanza-analytics/`
