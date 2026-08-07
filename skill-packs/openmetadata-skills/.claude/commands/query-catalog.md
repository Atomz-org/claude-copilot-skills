---
description: Ask the OpenMetadata catalog about a data asset — find tables, read a column's definition and PII tags, or trace column lineage back to the raw source
argument-hint: "[question, e.g. \"find tables related to orders\"] [use-case slug]"
---

# /query-catalog

0. Load the `openmetadata-catalog` skill and follow
   `.claude/rules/openmetadata-rules.md`.

1. **Answer from the artifact when the artifact holds the answer.** Meaning,
   additivity, PII class, and raw-source lineage all live in
   `<use-case>/ontology/column-annotations.json` and `column-memory.json`, and
   need no server. `<use-case>/openmetadata/knowledge/catalog.md` states what the
   catalog does and does not carry. Use the server for discovery questions —
   does this exist, what is it called, what is near it — and for "what does a
   catalog user see".

2. **Check the credentials before reaching out.** `OPENMETADATA_SERVER_URL` and
   `OPENMETADATA_AUTH_TOKEN` come from the environment. If either is unset, say
   so plainly and answer from the artifacts; do not guess a host.

3. **Query.** Search: `GET /api/v1/search/query?q=<term>&index=table_search_index`.
   One asset: `GET /api/v1/tables/name/<fqn>?fields=columns,tags,owners`. Lineage:
   `GET /api/v1/lineage/table/name/<fqn>?upstreamDepth=3`. Glossary:
   `GET /api/v1/glossaryTerms/name/<glossary>.<term>`. A running server also
   speaks MCP — the registration block is in the use-case's
   `openmetadata/knowledge/mcp.md`.

4. **Report tags precisely.** `PII.Sensitive` means do not put it on a shared
   dashboard. `ColumnAdditivity.NonAdditive` means `SUM()` is wrong, not slow.
   `DataProvenance.DltSystemColumn` means load bookkeeping, not business data.
   **An untagged column is undecided, not safe** — say "no additivity has been
   recorded for this column", never "it is additive".

5. **If the answer is stale or missing**, the fix is in the repository, not the
   UI: `python3 scripts/use_case_sync.py --use-case <slug> --stage openmetadata`,
   then a push. Never edit the catalog to correct it (rule 1).

6. **Pushing is data egress.** `--push` sends this use-case's definitions and
   lineage to the configured server. Run `--dry-run` first, show the request
   counts, and get explicit confirmation before the real push (rule 16).
