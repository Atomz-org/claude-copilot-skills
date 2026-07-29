#!/usr/bin/env python3
"""Generate a schema.yml skeleton for a dbt Core model, with tests inferred from column
names and types.

Reads manifest.json for the model's structure and catalog.json (from `dbt docs generate`)
for real warehouse column names and types — which is also what a contract's `data_type`
must match.

    dbt parse && dbt docs generate
    python scripts/schema_yml_generator.py --manifest target/manifest.json \
        --model stg_shopify__orders --catalog target/catalog.json --infer-tests

Output is a FIRST DRAFT. It gives you every column and a sensible test guess; you supply
the grain, the descriptions, and the business rules. A generated description that
restates the column name is worse than none.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _manifest import Colors, Manifest, load_json  # noqa: E402

# column-name pattern -> (tests, note)
NAME_RULES: List[Tuple[re.Pattern, List[str], str]] = [
    (re.compile(r"^(id|.*_id)$", re.I), ["not_null"], "identifier"),
    (re.compile(r"^(is|has)_", re.I), ["not_null"], "boolean flag"),
    (re.compile(r"_(status|type|category|state|tier|kind)$", re.I),
     ["not_null", "__accepted_values__"], "looks like a closed domain"),
    (re.compile(r"_(at|date|time|timestamp)$", re.I), ["not_null"], "temporal"),
    (re.compile(r"_(amount|amount_usd|revenue|price|cost|total)$", re.I),
     ["not_null", "__range__"], "monetary"),
    (re.compile(r"_(count|qty|quantity)$", re.I), ["__range__"], "count"),
    (re.compile(r"^(email|.*_email)$", re.I), [], "PII — check masking policy"),
    (re.compile(r"(phone|ssn|dob|birth|address|ip_address)", re.I), [],
     "PII — check masking policy"),
]


def indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line else line for line in text.splitlines())


def catalog_columns(catalog: Dict[str, Any], uid: str) -> Dict[str, str]:
    node = (catalog.get("nodes", {}) or {}).get(uid) or (
        catalog.get("sources", {}) or {}
    ).get(uid)
    if not node:
        return {}
    return {
        name: (meta or {}).get("type", "")
        for name, meta in (node.get("columns") or {}).items()
    }


def infer_tests(column: str, dtype: str, is_pk_guess: bool) -> Tuple[List[str], str]:
    tests: List[str] = []
    note = ""
    for pattern, rule_tests, rule_note in NAME_RULES:
        if pattern.search(column):
            tests = list(rule_tests)
            note = rule_note
            break
    if is_pk_guess:
        tests = ["unique", "not_null"]
        note = "primary key (guessed from the name — CONFIRM the grain)"
    return tests, note


def guess_primary_key(model_name: str, columns: List[str]) -> Optional[str]:
    """Guess the PK column. Always flagged in the output for human confirmation."""
    entity = re.sub(r"^(stg_[a-z0-9]+__|int_|fct_|dim_|rpt_|agg_|bridge_)", "", model_name)
    entity = entity.rstrip("s")
    candidates = [
        f"{entity}_id",
        f"{entity}s_id",
        f"{model_name}_id",
        f"{entity}_sk",
        f"{entity}_key",
        "id",
    ]
    lowered = {c.lower(): c for c in columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    # Fall back to a single trailing _id column, if there is exactly one.
    id_cols = [c for c in columns if c.lower().endswith("_id")]
    return id_cols[0] if len(id_cols) == 1 else None


def render(model_name: str, layer: str, columns: Dict[str, str],
           existing: Dict[str, Any], pk: Optional[str], infer: bool,
           contract: bool) -> str:
    lines: List[str] = ["version: 2", "", "models:", f"  - name: {model_name}"]

    desc = (existing.get("description") or "").strip()
    if desc:
        lines.append("    description: >")
        lines.append(indent(desc, 6))
    else:
        lines.append("    description: >")
        lines.append("      [NEEDS INPUT] One row per <entity> per <period>.")
        lines.append("      Excludes: <filters, test accounts, date cutoffs>.")
        lines.append("      Non-obvious: <why a join is left, what a null means, "
                     "which source wins>.")

    if contract:
        lines.append("    config:")
        lines.append("      contract: {enforced: true}")

    lines.append("    columns:")
    existing_cols = existing.get("columns") or {}

    for column, dtype in columns.items():
        meta = existing_cols.get(column) or {}
        lines.append(f"      - name: {column}")

        col_desc = (meta.get("description") or "").strip()
        if col_desc:
            lines.append(f"        description: {col_desc}")
        else:
            lines.append(f"        description: \"[NEEDS INPUT]\"")

        if contract and dtype:
            lines.append(f"        data_type: {dtype}")
        elif contract:
            lines.append("        data_type: \"[NEEDS INPUT — run dbt docs generate "
                         "and pass --catalog]\"")

        if not infer:
            continue

        tests, note = infer_tests(column, dtype, is_pk_guess=(column == pk))
        if not tests:
            if note:
                lines.append(f"        # {note}")
            continue

        lines.append("        data_tests:")
        for test in tests:
            if test == "__accepted_values__":
                lines.append("          # - accepted_values:")
                lines.append("          #     values: [<list the real domain>]")
            elif test == "__range__":
                lines.append("          # - dbt_utils.accepted_range:")
                lines.append("          #     min_value: 0")
                lines.append("          #     inclusive: true")
            else:
                lines.append(f"          - {test}")
        if note:
            lines.append(f"        # {note}")

    if infer:
        lines.append("")
        lines.append("    # Model-level tests to consider:")
        lines.append("    # data_tests:")
        lines.append("    #   - dbt_utils.unique_combination_of_columns:")
        lines.append("    #       combination_of_columns: [<the grain columns>]")
        lines.append("    #   - dbt_utils.expression_is_true:")
        lines.append("    #       expression: \"<a business invariant>\"")
        if layer == "marts":
            lines.append("    #")
            lines.append("    # Marts need an exposure. Add one in this file or the "
                         "domain's YAML:")
            lines.append("    # exposures:")
            lines.append("    #   - name: <consumer>")
            lines.append("    #     type: dashboard")
            lines.append("    #     owner: {name: <person>, email: <email>}")
            lines.append(f"    #     depends_on: [ref('{model_name}')]")

    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate a schema.yml skeleton for a dbt model."
    )
    ap.add_argument("--manifest", default="target/manifest.json")
    ap.add_argument("--model", required=True)
    ap.add_argument("--catalog", help="target/catalog.json — supplies real column types")
    ap.add_argument("--infer-tests", action="store_true",
                    help="suggest tests from column names and types")
    ap.add_argument("--contract", action="store_true",
                    help="emit contract: enforced with data_type on every column")
    ap.add_argument("--out", help="write to a file instead of stdout")
    args = ap.parse_args()

    man = Manifest.load(args.manifest)
    uid, model = man.find_model(args.model)
    name = model.get("name", args.model)

    from _manifest import layer_of  # local import keeps the CLI section tidy
    layer = layer_of(model)

    columns: Dict[str, str] = {}
    if args.catalog:
        if not os.path.exists(args.catalog):
            print(f"WARNING: catalog not found at {args.catalog}. Run "
                  f"`dbt docs generate`. Falling back to manifest columns.",
                  file=sys.stderr)
        else:
            columns = catalog_columns(load_json(args.catalog, "catalog.json"), uid)

    if not columns:
        columns = {c: (meta or {}).get("data_type") or ""
                   for c, meta in (model.get("columns") or {}).items()}

    if not columns:
        print(
            f"ERROR: no columns known for '{name}'.\n"
            f"  The manifest only knows columns that are already documented in YAML.\n"
            f"  Build the model, then `dbt docs generate`, then pass\n"
            f"  --catalog target/catalog.json to read the real warehouse columns.",
            file=sys.stderr,
        )
        return 2

    pk = guess_primary_key(name, list(columns))
    output = render(name, layer, columns, model, pk, args.infer_tests, args.contract)

    if args.out:
        if os.path.exists(args.out):
            print(f"ERROR: {args.out} already exists. Refusing to overwrite — "
                  f"write to a new path and merge by hand.", file=sys.stderr)
            return 2
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(output)
        print(f"Wrote {args.out}")
    else:
        print(output)

    notes = [
        f"Model: {name} ({layer}) — {len(columns)} columns"
        + (" from catalog" if args.catalog and columns else " from manifest"),
    ]
    if pk:
        notes.append(f"Guessed primary key: {pk} — CONFIRM this matches the grain "
                     f"before trusting the unique test.")
    else:
        notes.append("No primary key guessed. Every model needs one — a real column, "
                     "or a surrogate key over the grain columns.")
    if not args.catalog:
        notes.append("No --catalog: data_type values are missing or from YAML. A "
                     "contract needs the REAL warehouse types.")
    notes.append("Every [NEEDS INPUT] is deliberate. A description that restates the "
                 "column name is worse than none.")

    print(f"\n{Colors.BOLD}Notes{Colors.END}", file=sys.stderr)
    for note in notes:
        print(f"  - {note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
