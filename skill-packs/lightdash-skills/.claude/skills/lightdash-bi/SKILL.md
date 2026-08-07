---
name: lightdash-bi
description: Serve a use-case through Lightdash for BI and agentic analytics — derive explore joins, PII hiding, and AI hints from dbt artifacts, validate offline, and register the instance MCP. Triggers on "lightdash", "BI explore", "explore joins", "agentic BI", "lightdash compile", "lightdash deploy", "AI analyst".
license: MIT
metadata:
  upstream: "Lightdash (https://github.com/PackMaaan/lightdash fork of lightdash/lightdash; MIT with an EE-licensed packages/backend/src/ee carve-out), pinned as the external/lightdash submodule with @lightdash/cli at the same release"
---

# Lightdash BI — the serving tier for explores and agents

Lightdash reads a dbt project directly: models become explores, MetricFlow metrics are
translated natively by its CLI, and `meta` tags carry what dbt alone cannot say. This
repository's bridge (`scripts/lightdash_context_sync.py`) derives those meta tags from
evidence — never by hand, never invented:

| Meta | Derived from |
| --- | --- |
| `meta.joins` (explore joins) | dbt `relationships` tests |
| `relationship:` cardinality | `unique` tests, omitted where untested |
| `meta.primary_key` | the one unique+not_null tested column |
| `dimension.hidden: true` | `ontology/column-annotations.json` `pii: direct` |
| `dimension.ai_hint` | recorded definitions and additivity warnings |

What it never writes: **metrics**. The CLI translates MetricFlow definitions from the
manifest; the classes it cannot carry are served by the Wren views and named in
`lightdash/knowledge/semantic-coverage.md`. Follow
[lightdash-rules.md](../../rules/lightdash-rules.md) for the binding rules.

## Day to day

```bash
# regenerate the projection (meta tags + lightdash/knowledge/)
python3 scripts/use_case_sync.py --use-case <slug> --stage lightdash

# after meta changed: re-parse so the manifest carries it
./skill-packs/dbt-skills/use-cases/<slug>/artifacts/refresh.sh

# the no-server validation gate (CLI: npm install --prefix .lightdash-cli @lightdash/cli@1.97.0)
.lightdash-cli/node_modules/.bin/lightdash compile \
  --project-dir <dbt_project> --profiles-dir <dbt_project> \
  --skip-dbt-compile --skip-warehouse-catalog
```

## Agentic access

A running instance serves MCP at `/api/v1/mcp` (explores, fields, metric queries,
charts). The registration line and the credential rules are in the generated
`lightdash/knowledge/mcp.md` of each use-case — environment variables only, no tokens
on disk.

## Running an instance locally

`deploy/podman-compose.yml` in this pack starts Postgres plus a pinned Lightdash.
No repository bind mounts — `lightdash login` + `lightdash deploy` push the compiled
project instead, which is also why the stack works where `~/Documents` cannot be
mounted into containers. Deploying to any non-local instance is data egress and needs
explicit per-deploy confirmation (rule 9).
