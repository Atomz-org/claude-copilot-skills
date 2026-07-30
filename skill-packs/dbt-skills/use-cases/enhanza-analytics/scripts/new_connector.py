#!/usr/bin/env python3
"""Scaffold a new Enhanza connector.

Writes the directory layout, staging stubs, ERP adapter stubs, and user-facing one-liners
for a new source system, then prints the three config blocks that must be pasted by hand
(sources.yml, the registry entry, and the dbt_project.yml var + tag).

It deliberately does NOT edit sources.yml, global_configs.sql, or dbt_project.yml. Those
three are the connector's contract; a reviewer should see them arrive as a hand-written
diff, not as generated text. Everything it writes is a stub carrying [NEEDS INPUT] where a
real column list belongs — it saves the typing, not the modeling.

Existing files are never overwritten.

Usage:
    python3 scripts/new_connector.py shopify \\
        --display-name "Shopify" \\
        --currency USD \\
        --erp-concepts dim_customers,fact_orders \\
        --bi-models dim_customers,fact_orders,dim_discounts

See CONNECTORS.md for the full procedure.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent / "dbt_project"
MODELS = PROJECT / "models"

STAGING_STUB = """\
{{{{ config(alias=model_alias(model.name), enabled = var('is_{source}_enabled', false)) }}}}

-- Quarantines the raw {display} source: rename, cast, and coerce here and nowhere else.
-- Enumerate every column — `select *` must not survive past this layer.
-- [NEEDS INPUT] replace the column list with the real one from {source}_api.{table}

select
    -- RawColumnName as ColumnName
    *
from {{{{ source('{source}_api', '{table}') }}}}
"""

ADAPTER_STUB = """\
{{{{ config(materialized='ephemeral', enabled = var('is_{source}_enabled', false)) }}}}

-- Adapts {display} to the common ERP schema so erp_bi_{concept} can union it.
-- The output columns must match every other source's {concept} adapter exactly, in the
-- same order: a missing column fails the UNION ALL at compile time, but a column in the
-- wrong position with a compatible type silently transposes the data.
-- Compare against models/staging/fortnox/fortnox_erp_bi_{concept}.sql before merging.
-- [NEEDS INPUT] replace the column list

select
    -- ColumnName
    *
    {{{{ add_erp_fields([]) }}}}
from {{{{ ref('{source}_bi_{concept}_staging') }}}}
"""

BI_STUB = """\
{{ auto_config() }}
"""


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", value.strip().lower())


def write(path: Path, content: str, created: list, skipped: list) -> None:
    if path.exists():
        skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    created.append(path)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Scaffold a new Enhanza connector.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("source", help="registry key, e.g. shopify (lowercase, underscores)")
    p.add_argument("--display-name", help="human-readable name, e.g. Shopify")
    p.add_argument(
        "--currency",
        help="ISO code for default_currency. Omit if unconfirmed — a wrong currency "
        "silently mis-values every row, a missing one is emitted as NULL.",
    )
    p.add_argument(
        "--erp-concepts",
        default="",
        help="comma-separated unified concepts this source supplies, "
        "e.g. dim_customers,fact_orders",
    )
    p.add_argument(
        "--bi-models",
        default="",
        help="comma-separated source-aligned models. Defaults to --erp-concepts.",
    )
    args = p.parse_args()

    source = slug(args.source)
    if source != args.source:
        print(f"note: using '{source}' as the registry key", file=sys.stderr)
    display = args.display_name or source.replace("_", " ").title()

    erp_concepts = [slug(c) for c in args.erp_concepts.split(",") if c.strip()]
    bi_models = [slug(m) for m in args.bi_models.split(",") if m.strip()] or list(erp_concepts)

    missing = [c for c in erp_concepts if c not in bi_models]
    if missing:
        p.error(
            f"--erp-concepts {missing} have no matching --bi-models entry; every adapter "
            f"reads its source's own staging model"
        )

    if not (PROJECT / "dbt_project.yml").exists():
        p.error(f"dbt project not found at {PROJECT}")

    created: list[Path] = []
    skipped: list[Path] = []

    staging_dir = MODELS / "staging" / source
    bi_dir = MODELS / f"{source}_bi"

    for model in bi_models:
        write(
            staging_dir / f"{source}_bi_{model}_staging.sql",
            STAGING_STUB.format(source=source, display=display, table=model.split("_", 1)[-1]),
            created,
            skipped,
        )
        write(bi_dir / f"{source}_bi_{model}.sql", BI_STUB, created, skipped)

    for concept in erp_concepts:
        write(
            staging_dir / f"{source}_erp_bi_{concept}.sql",
            ADAPTER_STUB.format(source=source, display=display, concept=concept),
            created,
            skipped,
        )

    write(
        staging_dir / "schema.yml",
        "version: 2\n\nmodels:\n"
        + "".join(
            f"  - name: {source}_bi_{m}_staging\n"
            f"    description: '[NEEDS INPUT] one row per <entity>; "
            f"staged {display} {m}.'\n"
            for m in bi_models
        ),
        created,
        skipped,
    )
    write(
        bi_dir / "schema.yml",
        "version: 2\n\nmodels:\n"
        + "".join(
            f"  - name: {source}_bi_{m}\n"
            f"    description: '[NEEDS INPUT] one row per <entity>. "
            f"State the grain, not the model name.'\n"
            f"    columns:\n"
            f"      - name: [NEEDS INPUT]\n"
            f"        tests: [unique, not_null]\n"
            for m in bi_models
        ),
        created,
        skipped,
    )

    rel = lambda path: path.relative_to(PROJECT.parent)  # noqa: E731
    print(f"Scaffolded connector '{source}' ({display})\n")
    if created:
        print(f"Created {len(created)} file(s):")
        for f in sorted(created):
            print(f"  {rel(f)}")
    if skipped:
        print(f"\nLeft alone, already present ({len(skipped)}):")
        for f in sorted(skipped):
            print(f"  {rel(f)}")

    currency_line = (
        f"                'default_currency': '{args.currency}',"
        if args.currency
        else "                {#- default_currency omitted: unconfirmed. [NEEDS INPUT] -#}"
    )
    included = "\n".join(f"                    '{m}'," for m in sorted(set(bi_models)))

    print(
        f"""
--------------------------------------------------------------------------------
Now paste these three by hand. See CONNECTORS.md steps 2-4.
--------------------------------------------------------------------------------

1. dbt_project/models/sources.yml

  - name: {source}_api
    description: '{display} raw data'
    database: "{{{{ target.project | default(target.database) }}}}"
    schema: {source}_api_{{{{ var('uid') }}}}
    loaded_at_field: [NEEDS INPUT]
    freshness:
      warn_after: {{count: [NEEDS INPUT], period: hour}}
      error_after: {{count: [NEEDS INPUT], period: hour}}
    tables:
{chr(10).join(f"      - name: {m.split('_', 1)[-1]}" for m in bi_models)}

2. dbt_project/macros/config/global_configs.sql -> all_available_sources
   (alphabetically placed)

            '{source}': {{
                'name': '{display}',
{currency_line}
                'enabled': var('is_{source}_enabled', 'False') | as_bool,
                'included_models': [
{included.rstrip(',')}
                ]
            }},

3. dbt_project/dbt_project.yml

   under vars:                    is_{source}_enabled: false
   under models: -> staging:      {source}:
                                    +tags: ['{source}']
   and a sibling of favrit_bi:    {source}_bi:
                                    +tags: ['{source}', 'bi']

Then verify:
  python3 -m pytest tests/test_enhanza_connector_registry.py -q
  cd dbt_project && dbt parse --vars '{{"uid": "<tenant>", "is_{source}_enabled": true}}'
"""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
