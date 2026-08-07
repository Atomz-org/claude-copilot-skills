---
name: openmetadata-catalog
description: Query and publish the OpenMetadata data catalog for this repository's use-cases — search tables and dashboards, read a column's definition and PII tags, traverse column-level lineage, and regenerate or push the catalog bundle. Use when asked "find tables about X", "what does column Y mean", "is this column PII", "where does this value come from", "what is in the catalog", "publish to OpenMetadata", or "/query-catalog".
license: Apache-2.0
metadata:
  upstream: "OpenMetadata (https://github.com/open-metadata/OpenMetadata, Apache-2.0), server 1.13.3-release; standards from open-metadata/OpenMetadataStandards; optional runtime openmetadata-ingestion[dbt]==1.13.3.0"
---

# OpenMetadata — the discovery tier

OpenMetadata is the human-facing catalog over the same dbt use-cases WrenAI and
Lightdash serve. **The pipeline is unidirectional**: everything in the catalog
originates in this repository, and nothing in the catalog is ever read back into it.
Follow [openmetadata-rules.md](../../rules/openmetadata-rules.md).

## Answer from the artifact before you answer from the catalog

The catalog is a projection. For anything the repository holds, the artifact is the
authority and is available with no server, no token, and no network:

| Question | Read this first |
| --- | --- |
| What does this conformed column mean; can I `SUM()` it; is it PII | `<use-case>/ontology/column-annotations.json` |
| Which raw source column does this value come from | `<use-case>/ontology/column-memory.json` (`bindings`) |
| Which connectors supply this concept, which models realise it | `<use-case>/ontology/index.json` |
| What is in the catalog and what is deliberately not | `<use-case>/openmetadata/knowledge/catalog.md` |

Reach for the server when the question is about **discovery** — does a table exist,
what is it called, who owns it, what else is near it — or when the user is asking
about what a catalog *user* sees.

## Querying a running instance

Credentials come from the environment, never from a file:
`OPENMETADATA_SERVER_URL` (e.g. `http://localhost:8585/api`) and
`OPENMETADATA_AUTH_TOKEN`. If either is unset, say so and answer from the artifacts
instead of guessing an endpoint.

```bash
# find tables by name or description
curl -s -H "Authorization: Bearer $OPENMETADATA_AUTH_TOKEN" \
  "$OPENMETADATA_SERVER_URL/api/v1/search/query?q=orders&index=table_search_index&size=10"

# one table with its columns, tags, and description
curl -s -H "Authorization: Bearer $OPENMETADATA_AUTH_TOKEN" \
  "$OPENMETADATA_SERVER_URL/api/v1/tables/name/<service>.<db>.<schema>.<table>?fields=columns,tags,owners"

# column-level lineage, upstream to the raw source
curl -s -H "Authorization: Bearer $OPENMETADATA_AUTH_TOKEN" \
  "$OPENMETADATA_SERVER_URL/api/v1/lineage/table/name/<fqn>?upstreamDepth=3&downstreamDepth=1"

# a glossary term
curl -s -H "Authorization: Bearer $OPENMETADATA_AUTH_TOKEN" \
  "$OPENMETADATA_SERVER_URL/api/v1/glossaryTerms/name/<glossary>.<term>"
```

A running server also speaks MCP; the registration block is in each use-case's
generated `openmetadata/knowledge/mcp.md` — environment placeholders only.

### Reading the tags

- `PII.Sensitive` — direct personal data. Do not put it on a shared dashboard.
- `ColumnPII.Quasi` / `ColumnPII.Indirect` — identifying in combination or through a
  join. Masking is usually the *wrong* remedy; the risk is in the join.
- `ColumnAdditivity.NonAdditive` / `.SemiAdditive` — `SUM()` produces a plausible
  number that is wrong. Non-additive means never; semi-additive means not across time.
- `ColumnRole.Identifier` — numeric type, but arithmetic on it is always a bug.
- `DataProvenance.DltSystemColumn` — inserted by a dlt load. Load bookkeeping, never a
  grain and never a metric.
- **No tag is not a tag.** An untagged column has had no decision recorded. Never read
  a missing `ColumnAdditivity` tag as "additive"; check
  `column-annotations.json`'s `unannotated` list and say the column is undecided.

## Regenerating the bundle

```bash
# the one regeneration path (glossary, tags, column lineage, dlt provenance, RDF)
python3 scripts/use_case_sync.py --use-case <slug> --stage openmetadata

# the CI gate form — the bundle is committed, so this compares bytes
python3 scripts/use_case_sync.py --all --stage openmetadata --check
```

The bundle lands in `<use-case>/openmetadata/`:

| Path | Holds |
| --- | --- |
| `ingestion/dbt.yaml` | upstream's dbt connector config — the mechanical layer |
| `bundle/column-lineage.json` | `AddLineageRequest` per table pair, column to column |
| `bundle/glossary.json` | concept and conformed-column terms |
| `bundle/classifications.json` | the facet classifications and their tags |
| `bundle/tag-applications.json` | which tag lands on which column FQN |
| `bundle/dlt-provenance.json` | dlt load columns and system tables |
| `rdf/openmetadata-alignment.ttl` | the topology in OpenMetadata's own RDF vocabulary |
| `knowledge/` | what to read before asking the catalog anything |

## Publishing — egress, every time

```bash
# 1. the mechanical layer: tables, dbt tests, model-level lineage (upstream's connector)
pip install 'openmetadata-ingestion[dbt]==1.13.3.0'      # must match the server version
metadata ingest -c <use-case>/openmetadata/ingestion/dbt.yaml

# 2. count the requests without sending any
python3 scripts/openmetadata_sync.py --use-case <slug> --push --dry-run

# 3. the enrichment layer — ONLY after explicit user confirmation
python3 scripts/openmetadata_sync.py --use-case <slug> --push
```

**Stop and ask before step 3, every time** (rule 17). It sends this use-case's
glossary, definitions, and lineage to whatever server `OPENMETADATA_SERVER_URL`
names. Run `--dry-run` first and show the counts.

The push is deliberately incapable of deleting anything, and it creates no tables: if
a table is missing on the server, run step 1.

## Running an instance locally

`deploy/README.md` in this pack has the runbook. It uses upstream's own compose file
at the pinned release rather than a fork of it — the topology (server, database,
search, ingestion scheduler) is upstream's to change.
