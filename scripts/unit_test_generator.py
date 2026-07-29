#!/usr/bin/env python3
"""Scaffold a dbt Core unit test for a model, with every ref/source stubbed.

The most common unit-test failure is "input X is not mocked" — dbt requires every
ref() and source() in the model to appear in `given`. This reads them from the manifest
so none are missed, and types the placeholder literals for your adapter.

    dbt parse && dbt docs generate
    python scripts/unit_test_generator.py --manifest target/manifest.json \
        --model int_order_items --catalog target/catalog.json --adapter snowflake

The generator supplies STRUCTURE, not semantics. You write the input values and the
expected output BY HAND — expected output derived from the model's own expression
proves only that the expression equals itself.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _manifest import Colors, Manifest, load_json  # noqa: E402

# Adapter -> notes that actually change how you write fixtures.
ADAPTER_NOTES = {
    "snowflake": [
        "Date/timestamp literals are VARCHAR unless cast — use format: sql if a "
        "comparison fails inexplicably.",
        "Unquoted identifiers uppercase. numeric(28,6) vs 100.0 can mismatch on scale.",
    ],
    "bigquery": [
        "Strictest types of any adapter: INT64 / NUMERIC / FLOAT64 must match exactly.",
        "DATE, DATETIME, and TIMESTAMP are three different types and do not compare.",
        "Untyped nulls break union all — use cast(null as <type>) in format: sql.",
        "STRUCT and ARRAY columns require format: sql.",
    ],
    "postgres": [
        "numeric vs float8 mismatches are common; '' is not null.",
        "Rich :: casting makes format: sql easy here.",
    ],
    "redshift": [
        "varchar(256) default truncates long test strings.",
        "Use true/false literals for booleans, never 1/0.",
        "Prefer format: sql for anything typed.",
    ],
    "databricks": [
        "DECIMAL scale must match exactly.",
        "Nulls in union all need cast(null as <type>).",
        "MAP/STRUCT fixtures require format: sql.",
    ],
    "spark": ["Same as databricks: explicit DECIMAL scale and typed nulls."],
    "duckdb": ["Most permissive adapter — good for developing tests before running "
               "them against the real one."],
}

TYPE_PLACEHOLDER = [
    (re.compile(r"(int|bigint|smallint|integer|int64|number\(\d+,\s*0\))", re.I), "1"),
    (re.compile(r"(numeric|decimal|float|double|real)", re.I), "100.00"),
    (re.compile(r"(bool)", re.I), "true"),
    (re.compile(r"(timestamp|datetime)", re.I), "'2024-01-15 10:30:00'"),
    (re.compile(r"(^date$|_date)", re.I), "'2024-01-15'"),
    (re.compile(r"(char|text|string|varchar)", re.I), "'a'"),
]

NAME_PLACEHOLDER = [
    (re.compile(r"_id$|^id$", re.I), "'1'"),
    (re.compile(r"^(is|has)_", re.I), "true"),
    (re.compile(r"_(at|timestamp)$", re.I), "'2024-01-15 10:30:00'"),
    (re.compile(r"_date$", re.I), "'2024-01-15'"),
    (re.compile(r"_(amount|price|cost|revenue|total)", re.I), "100.00"),
    (re.compile(r"_(count|qty|quantity)$", re.I), "1"),
    (re.compile(r"_(status|type|state|category)$", re.I), "'pending'"),
]


def placeholder(column: str, dtype: str) -> str:
    for pattern, value in NAME_PLACEHOLDER:
        if pattern.search(column):
            return value
    for pattern, value in TYPE_PLACEHOLDER:
        if dtype and pattern.search(dtype):
            return value
    return "'a'"


def sql_cast(column: str, dtype: str, adapter: str) -> str:
    value = placeholder(column, dtype)
    if not dtype:
        return f"{value} as {column}"
    return f"cast({value} as {dtype}) as {column}"


def columns_for(man: Manifest, catalog: Dict[str, Any], uid: str) -> Dict[str, str]:
    node = (catalog.get("nodes", {}) or {}).get(uid) or (
        catalog.get("sources", {}) or {}
    ).get(uid)
    if node:
        return {
            name: (meta or {}).get("type", "")
            for name, meta in (node.get("columns") or {}).items()
        }
    src = man.all_nodes().get(uid, {})
    return {
        name: (meta or {}).get("data_type") or ""
        for name, meta in (src.get("columns") or {}).items()
    }


def input_expr(man: Manifest, uid: str) -> str:
    node = man.all_nodes().get(uid, {})
    if uid.startswith("source."):
        return f"source('{node.get('source_name')}', '{node.get('name')}')"
    return f"ref('{node.get('name', uid.split('.')[-1])}')"


def render_rows_dict(columns: Dict[str, str], n: int = 2) -> List[str]:
    lines = []
    for i in range(n):
        parts = []
        for col, dtype in columns.items():
            value = placeholder(col, dtype)
            if value == "'1'" and i:
                value = f"'{i + 1}'"
            parts.append(f"{col}: {value}")
        lines.append("          - {" + ", ".join(parts) + "}")
    return lines


def render_rows_sql(columns: Dict[str, str], adapter: str, n: int = 2) -> List[str]:
    lines = []
    for i in range(n):
        casts = []
        for col, dtype in columns.items():
            expr = sql_cast(col, dtype, adapter)
            if expr.startswith("cast('1' ") and i:
                expr = expr.replace("cast('1' ", f"cast('{i + 1}' ", 1)
            casts.append(expr)
        lines.append("          select " + ", ".join(casts))
        if i < n - 1:
            lines.append("          union all")
    return lines


def build(man: Manifest, catalog: Dict[str, Any], model_name: str, uid: str,
          model: Dict[str, Any], fmt: str, adapter: str,
          incremental: bool) -> str:
    parents = [
        p for p in (model.get("depends_on", {}).get("nodes", []) or [])
        if p.startswith(("model.", "source.", "snapshot.", "seed."))
    ]

    out: List[str] = ["unit_tests:"]

    def emit_test(test_name: str, description: str,
                  overrides: Optional[List[str]] = None,
                  mock_this: bool = False) -> None:
        out.append(f"  - name: {test_name}")
        out.append(f"    model: {model_name}")
        out.append("    description: >")
        out.append(f"      {description}")
        if overrides:
            out.extend(overrides)
        out.append("    given:")
        if not parents:
            out.append("      # This model has no refs or sources — nothing to mock.")
        for parent in parents:
            cols = columns_for(man, catalog, parent)
            out.append(f"      - input: {input_expr(man, parent)}")
            if fmt != "dict":
                out.append(f"        format: {fmt}")
            out.append("        rows:")
            if not cols:
                out.append("          # [NEEDS INPUT] no columns known for this input.")
                out.append("          # Run `dbt docs generate` and pass --catalog, or")
                out.append("          # list the columns the model actually reads.")
                out.append("          - {}")
            elif fmt == "sql":
                out.extend(render_rows_sql(cols, adapter))
            else:
                out.extend(render_rows_dict(cols))
        if mock_this:
            out.append("      # `this` mocks the model's own existing table — required")
            out.append("      # for the is_incremental() filter to be exercised at all.")
            own_cols = columns_for(man, catalog, uid)
            out.append("      - input: this")
            out.append("        rows:")
            if own_cols:
                out.extend(render_rows_dict(own_cols, n=1))
            else:
                out.append("          - {}   # [NEEDS INPUT]")
        out.append("    expect:")
        out.append("      rows:")
        out.append("        # [NEEDS INPUT] Write the expected output BY HAND from the")
        out.append("        # requirement. Deriving it with the model's own expression")
        out.append("        # proves only that the expression equals itself.")
        out.append("        # List ONLY the columns this test asserts — extra columns in")
        out.append("        # the model output are ignored, and a test that lists all of")
        out.append("        # them breaks on every unrelated change.")
        out.append("        - {}")
        out.append("")

    emit_test(
        f"test_{model_name}_happy_path",
        "[NEEDS INPUT] Describe the ONE behavior this test proves.",
    )
    emit_test(
        f"test_{model_name}_edge_cases",
        "[NEEDS INPUT] Nulls, zero, negative, empty string, unknown enum value, "
        "boundary dates, duplicate keys, missing parent.",
    )

    if incremental:
        emit_test(
            f"test_{model_name}_full_refresh",
            "Full-refresh path: is_incremental() is false, so nothing is filtered out.",
            overrides=["    overrides:", "      macros:", "        is_incremental: false"],
        )
        emit_test(
            f"test_{model_name}_incremental_window",
            "Incremental path: rows outside the lookback window must be excluded. "
            "This is the least-observed code in most projects.",
            overrides=["    overrides:", "      macros:", "        is_incremental: true"],
            mock_this=True,
        )

    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Scaffold a dbt unit test with every ref/source stubbed."
    )
    ap.add_argument("--manifest", default="target/manifest.json")
    ap.add_argument("--model", required=True)
    ap.add_argument("--catalog", help="target/catalog.json — supplies real column types")
    ap.add_argument("--format", choices=["dict", "csv", "sql"], default="dict")
    ap.add_argument("--adapter", help="snowflake | bigquery | postgres | redshift | "
                                      "databricks | spark | duckdb (defaults to the "
                                      "manifest's adapter_type)")
    ap.add_argument("--out", help="write to a file instead of stdout")
    args = ap.parse_args()

    if args.format == "csv":
        print("NOTE: csv fixtures are best for many rows. This generator emits dict or "
              "sql; use --format sql when types matter, then convert if you want csv.",
              file=sys.stderr)

    man = Manifest.load(args.manifest)
    uid, model = man.find_model(args.model)
    name = model.get("name", args.model)
    adapter = (args.adapter or man.adapter_type or "").lower()

    catalog: Dict[str, Any] = {}
    if args.catalog:
        if os.path.exists(args.catalog):
            catalog = load_json(args.catalog, "catalog.json")
        else:
            print(f"WARNING: catalog not found at {args.catalog}; column types will be "
                  f"missing. Run `dbt docs generate`.", file=sys.stderr)

    cfg = model.get("config", {}) or {}
    incremental = cfg.get("materialized") == "incremental"
    fmt = "sql" if args.format == "csv" else args.format

    output = build(man, catalog, name, uid, model, fmt, adapter, incremental)

    if args.out:
        if os.path.exists(args.out):
            print(f"ERROR: {args.out} exists. Refusing to overwrite — write to a new "
                  f"path and merge by hand.", file=sys.stderr)
            return 2
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(output + "\n")
        print(f"Wrote {args.out}")
    else:
        print(output)

    err = sys.stderr
    print(f"\n{Colors.BOLD}Notes{Colors.END}", file=err)
    parents = [
        p for p in (model.get("depends_on", {}).get("nodes", []) or [])
        if p.startswith(("model.", "source.", "snapshot.", "seed."))
    ]
    print(f"  - Stubbed {len(parents)} input(s). dbt errors if any ref/source in the "
          f"model is missing from `given`.", file=err)
    if incremental:
        print("  - Incremental model: two extra tests generated for the "
              "is_incremental() branches, including an `input: this` mock.", file=err)
    if not catalog:
        print("  - No catalog supplied, so column types are missing. Run "
              "`dbt docs generate` and pass --catalog for typed fixtures.", file=err)
    for note in ADAPTER_NOTES.get(adapter, []):
        print(f"  - [{adapter}] {note}", file=err)
    if adapter and adapter not in ADAPTER_NOTES:
        print(f"  - Unknown adapter '{adapter}' — no type guidance available.", file=err)
    print("  - If a test fails with an inexplicable comparison error, switch that input "
          "to format: sql and cast explicitly. That fixes most of them.", file=err)
    print("  - Test ONE behavior per test, and name it after that behavior.", file=err)
    return 0


if __name__ == "__main__":
    sys.exit(main())
