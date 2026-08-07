---
description: Serve a use-case through Lightdash — regenerate its meta projection, validate offline, and answer BI questions through the instance MCP
argument-hint: "[use-case slug, defaults to example-order-revenue-mart] [question or task]"
---

# /lightdash

0. Load the `lightdash-bi` skill and follow `.claude/rules/lightdash-rules.md`. If the
   CLI is missing: `npm install --prefix .lightdash-cli @lightdash/cli@1.97.0`.
1. Regenerate only if inputs changed (schema tests, annotations, metrics):
   `python3 scripts/use_case_sync.py --use-case <slug> --stage lightdash` — then
   `artifacts/refresh.sh` if it reported changed meta, so the manifest carries it.
2. Validate offline: the stage's compile verdict, or directly
   `.lightdash-cli/node_modules/.bin/lightdash compile --project-dir <dbt_project>
   --profiles-dir <dbt_project> --skip-dbt-compile --skip-warehouse-catalog`
   (the install is repo-local; bare `lightdash` is not on PATH).
3. For questions against a running instance, use the MCP registration in the
   use-case's `lightdash/knowledge/mcp.md` (env vars only, never tokens on disk).
4. `lightdash deploy` / previews to a non-local instance: stop and get explicit
   per-deploy confirmation first (rule 9 — data egress).
