---
name: marketplace-portability-patterns
description: Apply multi-harness marketplace portability patterns for skill packs, including plugin manifests and SKILL.md reference-splitting checks.
---

# Marketplace Portability Patterns

Use this skill when maintaining reusable skill packs that need to remain portable across multiple agent harnesses.

## Core patterns

- Keep one source-of-truth per pack at `skill-packs/<pack>/.claude`.
- Add a pack manifest at `skill-packs/<pack>/.claude-plugin/plugin.json`.
- Keep large SKILL.md files concise and move deep detail into `references/`.
- Validate portability in CI with deterministic checks.

## Local check command

```bash
./scripts/marketplace_portability_check.sh
```
