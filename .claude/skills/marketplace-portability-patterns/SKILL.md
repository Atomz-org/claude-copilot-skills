---
name: marketplace-portability-patterns
description: Apply multi-harness marketplace portability patterns for skill packs, including plugin manifests and `SKILL.md` reference-splitting checks.
---

# Marketplace Portability Patterns

Use this skill when maintaining reusable skill packs that need to remain portable across multiple agent harnesses.

## Core patterns

- Keep one source-of-truth per pack at `skill-packs/<pack>/.claude`.
- Add a pack manifest at `skill-packs/<pack>/.claude-plugin/plugin.json`.
- Keep large `SKILL.md` files concise and move deep detail into `references/`.
- Validate portability in CI with deterministic checks.

## Local check command

```bash
./scripts/marketplace_portability_check.sh
```

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| `/marketplace-portability` | The check run for real, with each failure explained as a fix rather than a byte count |
| "I added a skill — is the pack still portable?" | Manifest presence and the 8 KB / `references/` rule verified for the new skill |
| "my `SKILL.md` is too big" | The split: what stays inline, what moves to `references/`, and the link that has to resolve in both locations |

**Worked example**

> `/marketplace-portability`

```
$ ./scripts/marketplace_portability_check.sh
ERROR: skill-packs/dbt-skills/.claude/skills/data-modeling/SKILL.md is 15099 bytes (> 8192) and has no references/ directory

Fix
  Keep the decision content inline — when to use each level, the grain rules, the anti-patterns.
  Move the long-form catalogs (fact/dimension types, SCD 0-6, paradigm comparison) to
  skill-packs/dbt-skills/references/data_modeling.md, then add a trailing markdown link
  from `SKILL.md` to the relative path ../../../references/data_modeling.md

  That path resolves inside the pack and again at the repository root after activation, so
  the reference file must exist in both. ./scripts/activate_skill_stack.sh dbt-skills
  materialises the root copy, and tests/test_docs_links.py fails if either side is missing.
```

Re-run the check after the split; passing output is a single line, `Marketplace portability
checks passed.`
