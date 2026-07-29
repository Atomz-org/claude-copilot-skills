#!/usr/bin/env python3
"""Generate a Mermaid entity-relationship diagram from a dbt Core manifest.

Reads target/manifest.json (optionally target/catalog.json for real warehouse types) and
emits an `erDiagram` showing models as entities, their columns as attributes, and the
relationships between them.

Relationships are inferred from three signals, strongest first:

  1. `relationships` data tests   — an explicit, tested foreign key. Solid line.
  2. foreign-key column naming    — `customer_id` on a fact when `dim_customers` exists.
                                    Dashed line: plausible but untested.
  3. nothing                      — a ref() edge with no shared key is a lineage edge,
                                    not a relationship, and is deliberately not drawn.

Cardinality reflects reality rather than intent: an FK with a `not_null` test is drawn as
mandatory, one without it as optional, because that is what a consumer's join will hit.

    dbt parse
    python scripts/erd_generator.py --manifest target/manifest.json --layer marts

Never connects to a warehouse.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _manifest import (  # noqa: E402
    Colors,
    Manifest,
    die,
    header,
    layer_of,
    load_json,
    section,
    table,
    tested_columns,
)

FK_SUFFIXES = ("_id", "_sk", "_key", "_fk")
# Columns that look like keys but never point at a dimension.
FK_STOPWORDS = {
    "id", "_id", "sk", "key", "primary_key", "surrogate_key", "hash_key", "hashkey",
}


def entity_name(model_name: str) -> str:
    """Mermaid entity id: uppercase, alphanumerics and underscores only."""
    return re.sub(r"[^A-Za-z0-9_]", "_", model_name).upper()


def safe_type(raw: Optional[str]) -> str:
    """Mermaid attribute types must be a single bare token."""
    if not raw:
        return "unknown"
    token = re.sub(r"[^A-Za-z0-9_]+", "_", str(raw)).strip("_")
    return (token or "unknown")[:24]


def classify(name: str, node: Dict[str, Any]) -> str:
    """fact / dimension / bridge / aggregate / other, from the naming convention."""
    lowered = name.lower()
    if lowered.startswith("fct_") or lowered.startswith("fact_"):
        return "fact"
    if lowered.startswith("dim_"):
        return "dimension"
    if lowered.startswith("bridge_") or lowered.startswith("br_"):
        return "bridge"
    if lowered.startswith("agg_") or lowered.startswith("rpt_"):
        return "aggregate"
    if node.get("resource_type") == "snapshot":
        return "dimension"
    return "other"


class Relationship:
    def __init__(self, from_model: str, to_model: str, column: str,
                 tested: bool, mandatory: bool) -> None:
        self.from_model = from_model
        self.to_model = to_model
        self.column = column
        self.tested = tested
        self.mandatory = mandatory

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.from_model, self.to_model, self.column)

    def mermaid(self) -> str:
        # Left side is the referencing model (many), right side the referenced (one).
        right = "||" if self.mandatory else "o|"
        line = "--" if self.tested else ".."
        label = self.column if self.tested else f"{self.column}?"
        return (f"    {entity_name(self.from_model)} }}o{line}{right} "
                f"{entity_name(self.to_model)} : \"{label}\"")


def parse_ref_target(raw: Any) -> Optional[str]:
    """Pull the model name out of a relationships test's `to:` argument."""
    if not isinstance(raw, str):
        return None
    match = re.search(r"ref\(\s*['\"]([^'\"]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?\s*\)", raw)
    if match:
        # ref('package', 'model') -> the model is the last captured group present
        return match.group(2) or match.group(1)
    match = re.search(r"source\(\s*['\"][^'\"]+['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)", raw)
    if match:
        return match.group(1)
    return None


def collect_columns(node: Dict[str, Any], catalog_node: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """[(name, type, description)] preferring catalog types over declared ones."""
    cat_cols = {k.lower(): v for k, v in (catalog_node.get("columns") or {}).items()}
    out: List[Tuple[str, str, str]] = []
    declared = node.get("columns") or {}
    names = list(declared.keys())
    for name in cat_cols:
        if name not in {n.lower() for n in names}:
            names.append(cat_cols[name].get("name", name))
    for name in names:
        meta = declared.get(name) or {}
        cat = cat_cols.get(str(name).lower()) or {}
        dtype = meta.get("data_type") or cat.get("type")
        out.append((str(name), safe_type(dtype), str(meta.get("description") or "")))
    return out


def build(man: Manifest, catalog: Dict[str, Any], layers: Set[str],
          only: Optional[Set[str]]) -> Tuple[Dict[str, Dict[str, Any]], List[Relationship], List[str]]:
    """Return (selected models, relationships, notes)."""
    catalog_nodes = (catalog.get("nodes") or {}) if catalog else {}

    all_models: Dict[str, Dict[str, Any]] = {}
    all_models.update(man.models())
    all_models.update(man.snapshots())

    selected: Dict[str, Dict[str, Any]] = {}
    for uid, node in all_models.items():
        name = node.get("name", "")
        if only is not None:
            if name not in only:
                continue
        elif layers and layer_of(node) not in layers:
            continue
        selected[uid] = node

    if not selected:
        die("no models matched. Check --layer / --models against `dbt ls`.", code=1)

    name_to_uid = {n.get("name"): uid for uid, n in all_models.items()}
    selected_names = {n.get("name") for n in selected.values()}
    tests_by_model = man.tests_by_model()

    rels: Dict[Tuple[str, str, str], Relationship] = {}
    notes: List[str] = []

    # --- signal 1: relationships tests -------------------------------------------
    for uid, node in selected.items():
        name = node.get("name", "")
        tests = tests_by_model.get(uid, [])
        not_null_cols = {
            col for col, names in tested_columns(tests).items() if "not_null" in names
        }
        for test in tests:
            meta = test.get("test_metadata") or {}
            if (meta.get("name") or "").lower() != "relationships":
                continue
            kwargs = meta.get("kwargs") or {}
            target = parse_ref_target(kwargs.get("to"))
            column = test.get("column_name") or kwargs.get("column_name") or kwargs.get("field")
            if not target or not column:
                continue
            if target not in selected_names:
                notes.append(
                    f"{name}.{column} has a tested relationship to {target}, which is "
                    f"outside the selected scope — not drawn."
                )
                continue
            rel = Relationship(name, target, str(column), tested=True,
                               mandatory=str(column) in not_null_cols)
            rels[rel.key] = rel

    # --- signal 2: FK naming convention ------------------------------------------
    dim_lookup: Dict[str, str] = {}
    for uid, node in selected.items():
        name = node.get("name", "")
        if classify(name, node) != "dimension":
            continue
        stem = re.sub(r"^dim_", "", name.lower())
        dim_lookup[stem] = name
        dim_lookup[stem.rstrip("s")] = name          # dim_customers <- customer_id
        dim_lookup[stem + "s"] = name                # dim_customer  <- customers_id

    untested: List[Tuple[str, str, str]] = []
    for uid, node in selected.items():
        name = node.get("name", "")
        if classify(name, node) == "dimension":
            # dimension-to-dimension FKs are outriggers; still drawn, but they are rarer
            pass
        tests = tests_by_model.get(uid, [])
        not_null_cols = {
            col for col, names in tested_columns(tests).items() if "not_null" in names
        }
        for column, _dtype, _desc in collect_columns(node, catalog_nodes.get(uid, {})):
            lowered = column.lower()
            if lowered in FK_STOPWORDS or not lowered.endswith(FK_SUFFIXES):
                continue
            stem = lowered
            for suffix in FK_SUFFIXES:
                if stem.endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            if not stem:
                continue
            target = dim_lookup.get(stem)
            if not target or target == name:
                continue
            key = (name, target, column)
            if key in rels:
                continue
            rels[key] = Relationship(name, target, column, tested=False,
                                     mandatory=column in not_null_cols)
            untested.append((name, column, target))

    for from_model, column, target in untested:
        notes.append(
            f"{from_model}.{column} -> {target} inferred from naming only — no "
            f"`relationships` test. Drawn as a dashed line."
        )

    ordered = sorted(rels.values(), key=lambda r: (r.from_model, r.to_model, r.column))
    return selected, ordered, notes


def primary_key_columns(man: Manifest, selected: Dict[str, Dict[str, Any]]) -> Dict[str, Set[str]]:
    """model name -> columns carrying both `unique` and `not_null`."""
    tests_by_model = man.tests_by_model()
    out: Dict[str, Set[str]] = {}
    for uid, node in selected.items():
        keys = {
            col for col, names in tested_columns(tests_by_model.get(uid, [])).items()
            if "unique" in names and "not_null" in names
        }
        if keys:
            out[node.get("name", "")] = {k.lower() for k in keys}
    return out


def render(selected: Dict[str, Dict[str, Any]], rels: List[Relationship],
           catalog: Dict[str, Any], show_attrs: bool, max_columns: int,
           pk_by_model: Dict[str, Set[str]]) -> str:
    catalog_nodes = (catalog.get("nodes") or {}) if catalog else {}
    lines = ["erDiagram"]

    fk_by_model: Dict[str, Set[str]] = {}
    for rel in rels:
        fk_by_model.setdefault(rel.from_model, set()).add(rel.column.lower())

    if show_attrs:
        for uid, node in sorted(selected.items(), key=lambda kv: kv[1].get("name", "")):
            name = node.get("name", "")
            columns = collect_columns(node, catalog_nodes.get(uid, {}))
            if not columns:
                lines.append(f"    {entity_name(name)} {{")
                lines.append("        unknown no_columns_declared")
                lines.append("    }")
                continue
            lines.append(f"    {entity_name(name)} {{")
            shown = columns[:max_columns]
            for col, dtype, _desc in shown:
                marker = ""
                if col.lower() in pk_by_model.get(name, set()):
                    marker = " PK"
                elif col.lower() in fk_by_model.get(name, set()):
                    marker = " FK"
                lines.append(f"        {dtype} {re.sub(r'[^A-Za-z0-9_]', '_', col)}{marker}")
            if len(columns) > max_columns:
                lines.append(f"        more {len(columns) - max_columns}_more_columns")
            lines.append("    }")

    for rel in rels:
        lines.append(rel.mermaid())

    if not rels:
        lines.append("    %% No relationships found. Add `relationships` tests to your")
        lines.append("    %% foreign keys, or check that dimensions are named dim_<entity>.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate a Mermaid ER diagram from a dbt manifest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--manifest", default="target/manifest.json")
    ap.add_argument("--catalog", help="target/catalog.json, for real warehouse types")
    ap.add_argument("--layer", default="marts",
                    help="comma-separated layers to include, or 'all' (default: marts)")
    ap.add_argument("--models", help="comma-separated model names; overrides --layer")
    ap.add_argument("--no-attributes", action="store_true",
                    help="relationships only, no column lists")
    ap.add_argument("--max-columns", type=int, default=12,
                    help="columns shown per entity before truncating (default: 12)")
    ap.add_argument("--out", help="write the diagram to this file")
    ap.add_argument("--format", dest="fmt", choices=["mermaid", "markdown"],
                    default="mermaid", help="markdown wraps the diagram in a fenced block")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()

    if args.no_color or not sys.stdout.isatty():
        Colors.disable()

    man = Manifest.load(args.manifest)
    catalog = load_json(args.catalog, "catalog") if args.catalog else {}

    layers = set()
    if args.layer and args.layer.lower() != "all":
        layers = {piece.strip() for piece in args.layer.split(",") if piece.strip()}
    only = ({m.strip() for m in args.models.split(",") if m.strip()}
            if args.models else None)

    selected, rels, notes = build(man, catalog, layers, only)
    pk_by_model = primary_key_columns(man, selected)
    diagram = render(selected, rels, catalog, not args.no_attributes,
                     args.max_columns, pk_by_model)

    if args.fmt == "markdown":
        title = f"# ERD — {man.project_name}"
        body = f"{title}\n\n```mermaid\n{diagram}\n```\n"
        if notes:
            body += "\n## Notes\n\n" + "\n".join(f"- {n}" for n in notes) + "\n"
        body += (
            "\n> Solid lines are `relationships`-tested foreign keys. Dashed lines are "
            "inferred\n> from column naming and are **not** enforced by any test.\n"
        )
        output = body
    else:
        output = diagram

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(output if output.endswith("\n") else output + "\n")

    header(f"ERD — {man.project_name}")
    kinds: Dict[str, int] = {}
    for node in selected.values():
        kinds[classify(node.get("name", ""), node)] = kinds.get(
            classify(node.get("name", ""), node), 0) + 1
    print("  " + " · ".join(f"{count} {kind}" for kind, count in sorted(kinds.items())))
    tested_count = sum(1 for r in rels if r.tested)
    print(f"  {len(rels)} relationship(s): {tested_count} tested, "
          f"{len(rels) - tested_count} inferred from naming")

    section("Diagram")
    print(output if not args.out else f"  Wrote {args.out}")

    if notes:
        section(f"Notes ({len(notes)})")
        table([[n] for n in notes], ["note"], max_width=76)

    if not args.out:
        section("Relationships")
        table(
            [[r.from_model, r.column, r.to_model,
              "tested" if r.tested else "inferred",
              "mandatory" if r.mandatory else "optional"]
             for r in rels],
            ["from", "column", "to", "evidence", "cardinality"],
        )
        print("\n  An 'inferred' relationship has no `relationships` test — the join is")
        print("  a convention, not a guarantee. An 'optional' FK needs an unknown member")
        print("  row in the dimension, or every consumer's inner join silently drops rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
