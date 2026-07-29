---
description: Validate skill-pack portability checks inspired by multi-harness marketplace patterns.
---

Run portability checks for shared and domain skill packs.

1. Validate plugin manifests exist for each pack.
2. Validate oversized SKILL.md files include a `references/` directory for progressive disclosure.
3. Fail fast if a portability violation is detected.

Run:

```bash
./scripts/marketplace_portability_check.sh
```
