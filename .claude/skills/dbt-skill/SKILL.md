---
name: dbt-skill
description: Canonical dbt skill entrypoint for this repository. Routes dbt requests to the right focused skill and enforces dbt Core operating rules.
---

# dbt Skill

This is the canonical skill entrypoint for dbt work in this repository.

## Routing

- Start with [analytics-request-framing](../analytics-request-framing/SKILL.md).
- Continue with the stage-appropriate focused skills in this folder.
- Use specialist dbt agents from `../agents/` when decomposition is needed.

## Use-case path policy

All new dbt use-cases must be created under:

- `skill-packs/dbt-skills/use-cases/<slug>/`

Do not create new dbt use-cases under the repository root `use-cases/` path.

## Compatibility

`senior-analytics-engineer` remains as a compatibility alias and should route here.
