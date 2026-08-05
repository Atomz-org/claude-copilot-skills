#!/usr/bin/env python3
"""Generate referentially-coherent sample data for a dbt project's sources.

Seeds the **sources**, not the models. 359 models with a fixture each would be 359 files
that restate what the SQL already says and go stale the moment a model changes; four hundred
rows across the source tables let `dbt build` derive all 359, which both produces the sample
data and exercises the transformations that make it. A fixture that cannot fail is not
telling you anything.

Which columns to emit is not guessed. `scripts/dbt_column_lineage.py` parses every staging
model and reports exactly which source columns are read, so the generated CSVs carry the
columns the project actually consumes and nothing else. Adding a column to a staging model
adds it here on the next run; the sample data cannot fall behind the code that reads it.

Values come from `ontology/reference/*.csv` and nowhere else. The convention is
microsoft/Ontology-Playground's — a single source of truth for names, never invented at the
point of use — and it coincides with rule 5 in this repository. Where a column has no
reference mapping it gets a *structurally* valid placeholder (a typed, deterministic value)
rather than a plausible business one: `ART-100` is a real article number from the reference
file, `col_value_3` is visibly a placeholder, and neither can be mistaken for a fact.

Determinism matters as much as coherence. No randomness anywhere: the same manifest produces
byte-identical CSVs, so a diff means the project changed and never that the generator ran
again.

Usage:
    python3 scripts/dbt_seed_generator.py --use-case enhanza-analytics
    python3 scripts/dbt_seed_generator.py --use-case enhanza-analytics --connector fortnox
    python3 scripts/dbt_seed_generator.py --use-case enhanza-analytics --dry-run
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _manifest import Manifest, die  # noqa: E402

from _paths import REPO  # noqa: E402

ROWS_PER_TABLE = 12
EPOCH = date(2026, 1, 5)  # a Monday, so weekday-sensitive logic is stable

# Column-name shapes and the reference column that fills them. Order matters: the first
# match wins, so `CustomerNumber` resolves before the generic `*Number`.
NAME_RULES: Tuple[Tuple[str, str], ...] = (
    (r"^OrgId$", "org_id"),
    (r"^OrgName$", "org_name"),
    (r"(?i)^customer(number|no|code)$", "customer_number"),
    (r"(?i)^supplier(number|no|code)$", "supplier_number"),
    (r"(?i)^employee(number|no|code)$", "employee_number"),
    (r"(?i)^article(number|no|code)$", "article_number"),
    (r"(?i)^(article|product|item)name$", "article_name"),
    (r"(?i)^(name|companyname|client|company|customername|suppliername)$", "party_name"),
    (r"(?i)^unit$", "unit"),
    (r"(?i)^(currency|currencycode|defaultcurrency)$", "currency"),
    (r"(?i)^(account|accountnumber)$", "account_number"),
    (r"(?i)^city$", "city"),
    (r"(?i)^country(code)?$", "country"),
)

DATE_RE = re.compile(r"(?i)(date|_at|datetime|created|updated|modified|from|to)$")
BOOL_RE = re.compile(r"(?i)^(is[A-Z_]|active$|barred$|blocked$|deleted$|has[A-Z_])")
NUM_RE = re.compile(
    r"(?i)(amount|total|price|cost|sum|quantity|qty|balance|value|rate|percent|discount|weight|stock)"
)
ID_RE = re.compile(r"(?i)(id|number|no)$")


class Reference:
    """The reference data, loaded once. Nothing outside this class produces a name."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.orgs = self._read("organisations.csv")
        self.parties = self._read("parties.csv")
        self.articles = self._read("articles.csv")
        self.accounts = self._read("accounts.csv")
        self.currencies = self._read("currencies.csv")
        if not self.orgs:
            die(f"no reference data under {root} — see its README")
        self.customers = [p for p in self.parties if p["PartyKind"] == "customer"]
        self.suppliers = [p for p in self.parties if p["PartyKind"] == "supplier"]
        self.employees = [p for p in self.parties if p["PartyKind"] == "employee"]

    def _read(self, name: str) -> List[Dict[str, str]]:
        path = self.root / name
        if not path.exists():
            return []
        return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))

    def value(self, kind: str, index: int) -> Optional[str]:
        def pick(rows: List[Dict[str, str]], column: str) -> Optional[str]:
            return rows[index % len(rows)][column] if rows else None

        return {
            "org_id": lambda: pick(self.orgs, "OrgId"),
            "org_name": lambda: pick(self.orgs, "OrgName"),
            "customer_number": lambda: pick(self.customers, "PartyNumber"),
            "supplier_number": lambda: pick(self.suppliers, "PartyNumber"),
            "employee_number": lambda: pick(self.employees, "PartyNumber"),
            "party_name": lambda: pick(self.parties, "PartyName"),
            "article_number": lambda: pick(self.articles, "ArticleNumber"),
            "article_name": lambda: pick(self.articles, "ArticleName"),
            "unit": lambda: pick(self.articles, "Unit"),
            "currency": lambda: pick(self.currencies, "Code"),
            "account_number": lambda: pick(self.accounts, "Number"),
            "city": lambda: pick(self.parties, "City"),
            "country": lambda: pick(self.parties, "Country"),
        }.get(kind, lambda: None)()


def reference_kind(column: str) -> Optional[str]:
    for pattern, kind in NAME_RULES:
        if re.search(pattern, column):
            return kind
    return None


def cell(column: str, row: int, ref: Reference) -> str:
    """One deterministic value for one column.

    The ordering is the contract: reference data first, then structural types, then a
    visible placeholder. A column that reaches the placeholder branch is one the reference
    files do not cover — which is information, and is why the placeholder is deliberately
    not plausible.
    """
    kind = reference_kind(column)
    if kind:
        value = ref.value(kind, row)
        if value is not None:
            return value

    if BOOL_RE.search(column):
        return "true" if row % 3 else "false"
    if DATE_RE.search(column):
        return (EPOCH + timedelta(days=row * 7)).isoformat()
    if NUM_RE.search(column):
        # Stable, non-round, and never zero — a zero in sample data hides division bugs.
        return f"{(row + 1) * 137.5:.2f}"
    if ID_RE.search(column):
        # Referential integrity comes from the modulus: a fact row's CustomerId lands on a
        # dimension row that exists, because both index the same small ring of values.
        stem = re.sub(r"(?i)(id|number|no)$", "", column) or "KEY"
        return f"{stem[:6].upper()}-{row % ROWS_PER_TABLE + 1:03d}"
    return f"{column.lower()}_value_{row + 1}"


JINJA_SPAN = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
QUOTED = re.compile(r"'([A-Za-z_][A-Za-z0-9_.]*)'")


def _macro_argument_columns(man: Manifest) -> Dict[str, Set[str]]:
    """Columns a staging model reads *inside* jinja macro calls, per source relation.

    The sqlglot lineage parses raw SQL with jinja spans replaced by markers, so a column
    consumed only as a macro argument — `{{ blank_to_null('p.variant_sku') }}` — is
    invisible to it, and the first real load failed on a seed missing exactly that column.
    The arguments are still code, not guesswork: for a model that reads exactly one source
    and refs no other model (staging discipline, rule 19), a quoted identifier inside a
    jinja span can only be a column of that source. Models joining several sources are
    skipped rather than attributed ambiguously.
    """
    sep = None
    out: Dict[str, Set[str]] = {}
    for node in man.nodes.values():
        if node.get("resource_type") != "model":
            continue
        deps = node.get("depends_on", {})
        model_deps = [d for d in deps.get("nodes", []) if d.startswith("model.")]
        source_deps = [d for d in deps.get("nodes", []) if d.startswith("source.")]
        if model_deps or len(source_deps) != 1:
            continue
        src = man.sources.get(source_deps[0])
        if not src:
            continue
        if sep is None:
            import dbt_column_lineage as lineage_mod
            sep = lineage_mod.SOURCE_SEP
        key = f"{src.get('source_name')}{sep}{src.get('name')}"
        for span in JINJA_SPAN.findall(node.get("raw_code") or ""):
            if re.match(r"\s*(ref|source|config|var)\b", span):
                continue
            for quoted in QUOTED.findall(span):
                column = quoted.rsplit(".", 1)[-1]
                out.setdefault(key, set()).add(column)
    return out


def _referenced_source_columns(man: Manifest) -> Dict[str, Set[str]]:
    """Every column a model references against a source table, in *any* select scope.

    Output lineage is the wrong completeness bar for seeds, and the first real load proved
    it: the seventime adapter reads `unitPrice` into a CTE column its final select then
    discards, so the lineage — correctly — has no edge for it, and the seed built from
    lineage lacked a column the inlined SQL still selects. A seed must satisfy what the SQL
    *references*, not what survives to the output.

    Reuses dbt_column_lineage's own scope walkers (`_sources_of` reads only FROM/JOINs;
    `_row_aliases` keeps unnest row variables from being read as columns). Bare columns are
    attributed only when the scope reads exactly one relation and it is a source. Nested
    scopes can still over-attribute a column to an outer scope's sole source — for seeds
    that is a harmless extra CSV column, where the reverse (a missing one) is a failed
    build.
    """
    import dbt_column_lineage as lm
    from sqlglot import exp

    source_keys = {
        f"{s.get('source_name')}{lm.SOURCE_SEP}{s.get('name')}" for s in man.sources.values()
    }
    out: Dict[str, Set[str]] = {}
    for node in man.nodes.values():
        if node.get("resource_type") != "model":
            continue
        tree, _err = lm.parse_model_sql(node.get("raw_code") or "", lm.DEFAULT_DIALECT)
        if tree is None:
            continue
        # Not `_selects_of`: that walker deliberately excludes CTE bodies, because lineage
        # follows into a CTE only when an output column leads there. Here the CTE bodies
        # are the point — `with main as (select unitPrice ... from src)` reads the source
        # inside the CTE — so every Select in the tree is a scope.
        for select in tree.find_all(exp.Select):
            aliases, _tables = lm._sources_of(select)
            src_aliases = {a: t for a, t in aliases.items() if t in source_keys}
            if not src_aliases:
                continue
            rows = lm._row_aliases(select)
            sole = (
                next(iter(src_aliases.values()))
                if len(set(aliases.values())) == 1
                else None
            )
            for col in select.find_all(exp.Column):
                if col.name == lm.MACRO_MARKER or col.name in rows:
                    continue
                table = col.table
                if table:
                    if table in src_aliases and table not in rows:
                        out.setdefault(src_aliases[table], set()).add(col.name)
                elif sole:
                    out.setdefault(sole, set()).add(col.name)
    return out


def source_columns(man: Manifest) -> Dict[str, Tuple[str, Set[str]]]:
    """`{source_unique_id: (relation, columns actually read)}`, from the parsed SQL."""
    try:
        import dbt_column_lineage as lineage_mod
    except ImportError:  # pragma: no cover - ships beside this file
        return {}
    if lineage_mod.sqlglot is None:
        return {}

    lineage = lineage_mod.build_lineage(man)
    wanted: Dict[str, Set[str]] = {}
    for edge in lineage["edges"]:
        if edge.upstream_column in ("*", "(macro)") or not edge.upstream_model:
            continue
        wanted.setdefault(edge.upstream_model, set()).add(edge.upstream_column)
    for collector in (_referenced_source_columns, _macro_argument_columns):
        for key, columns in collector(man).items():
            wanted.setdefault(key, set()).update(columns)

    out: Dict[str, Tuple[str, Set[str]]] = {}
    sep = lineage_mod.SOURCE_SEP
    for uid, node in man.sources.items():
        key = f"{node.get('source_name')}{sep}{node.get('name')}"
        columns = set(wanted.get(key, set()))
        # Declared columns count even when no model reads them yet: sources.yml is a
        # contract, and a seed missing a contracted column makes the contract untestable.
        columns |= set((node.get("columns") or {}).keys())
        if columns:
            out[uid] = (key, columns)
    return out


def _relations_claimed_by_models(man: Manifest) -> Set[Tuple[str, str]]:
    """`{(source_name, table)}` for every source relation a model already writes.

    A seed lands at `schema=<source_name>`, `alias=<table>` — see `build_properties` — so a
    model whose own schema and alias resolve to that pair is competing for one relation.
    Compared on those two rather than on the fully-qualified name because the database and
    the target suffix are applied identically to both by `generate_schema_name()`, so they
    cannot distinguish a collision from a non-collision.
    """
    claimed: Set[Tuple[str, str]] = set()
    by_relation: Dict[Tuple[str, str], str] = {}
    for node in man.nodes.values():
        if node.get("resource_type") != "model":
            continue
        config = node.get("config") or {}
        schema = config.get("schema") or node.get("schema") or ""
        alias = node.get("alias") or node.get("name") or ""
        by_relation[(schema, alias)] = node.get("name", "")

    for node in man.sources.values():
        key = (node.get("source_name", ""), node.get("name", ""))
        if key in by_relation:
            claimed.add(key)
    return claimed


def build_seeds(man: Manifest, ref: Reference, connector: Optional[str]) -> Dict[str, str]:
    """`{filename: csv text}` — one file per source table with data behind it,
    plus `properties.yml` binding each seed to the source relation it stands in for."""
    seeds: Dict[str, str] = {}
    claimed = _relations_claimed_by_models(man)
    for uid, (relation, columns) in sorted(source_columns(man).items()):
        node = man.sources[uid]
        source_name = node.get("source_name", "")
        if connector and not source_name.startswith(connector):
            continue
        # A source table that a *model* also writes is not an upstream table, whatever the
        # `sources:` block says — it is a relation this project maintains and then reads
        # back. `app.dimension_categories` is exactly that: an incremental model merges into
        # it and a source block reads it. A seed standing in for it declares the same
        # `(schema, alias)` the model does, and dbt refuses to compile at all:
        #
        #   dbt found two resources with the database representation
        #   "enhanza_sample"."app_demo"."dimension_categories"
        #
        # which fails the whole project, not just the sample build. Skipping is right on the
        # merits too — the model already produces the rows a seed would be faking.
        if (source_name, node.get("name", "")) in claimed:
            continue
        # Case-colliding names are one column, not two. Different models spell the same
        # physical column differently (`DueDate` in one, `duedate` in another); BigQuery
        # resolves column references case-insensitively so both hit one column, and DuckDB
        # rejects a table that declares both ("Column with name enz_sync_ts already
        # exists"). Fold to one deterministic representative per lowercased name.
        variants: Dict[str, List[str]] = {}
        for c in columns:
            variants.setdefault(c.lower(), []).append(c)
        folded = {min(v) for v in variants.values()}
        # The tiebreak on `c` is what makes this deterministic, and it is not decoration.
        # `folded` is a set, so its iteration order varies with PYTHONHASHSEED, and a
        # stable sort would otherwise preserve whichever order the set happened to yield.
        # Two of 99 seeds flapped between runs before this, which is precisely the diff
        # that teaches a reviewer to ignore generated files.
        ordered = sorted(folded, key=lambda c: (c != "OrgId", c.lower(), c))
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(ordered)
        for row in range(ROWS_PER_TABLE):
            writer.writerow([cell(column, row, ref) for column in ordered])
        seeds[f"{relation}.csv"] = buffer.getvalue()
    if seeds:
        seeds["properties.yml"] = build_properties(seeds)
    return seeds


def build_properties(seeds: Dict[str, str]) -> str:
    """The wiring that makes a seed *be* its source table, written down once.

    A seed file is named `<source>__<table>.csv` because seed names are project-global and
    six connectors each have a `customers` table. But `source('fortnox_api', 'customers')`
    resolves to relation `customers` in schema `fortnox_api_<uid>` — so each seed declares
    the `alias` (strip the prefix) and `schema` (the source name) that land it exactly where
    the source lookup points, given the project's own generate_schema_name(): on a
    non-production target it emits `<custom>_<target.schema>`, so `+schema: fortnox_api` on
    target `demo` materialises at `fortnox_api_demo` = `fortnox_api_{{ var('uid') }}` with
    `uid: demo`. No edit to sources.yml, no second convention.

    `enabled` is gated to the demo target: these files exist for local, warehouse-free
    builds, and a `dbt seed` against production must not be able to drop 99 sample tables
    into the raw datasets.

    Every column is pinned `varchar`. A raw API landing table is string-typed, staging
    casts explicitly (rule 15 — that is what staging is *for*), and leaving types to
    inference means two inferrers: dbt's agate and the warehouse CSV sniffer, which
    disagreed on the first real load (agate INTEGER vs DuckDB VARCHAR) and failed the
    seed. One declared type, zero inference disputes.
    """
    lines = [
        "# GENERATED by scripts/dbt_seed_generator.py — do not edit.",
        "# Binds each sample seed to the source relation it stands in for; see README.md.",
        "version: 2",
        "",
        "seeds:",
    ]
    for name in sorted(seeds):
        stem = name[: -len(".csv")] if name.endswith(".csv") else name
        if "__" not in stem or not name.endswith(".csv"):
            continue
        source_name, table = stem.split("__", 1)
        header = seeds[name].splitlines()[0].split(",")
        lines += [
            f"  - name: {stem}",
            "    config:",
            f"      enabled: \"{{{{ target.name == 'demo' }}}}\"",
            f"      alias: {table}",
            f"      schema: {source_name}",
            "      column_types:",
        ]
        lines += [f"        {column}: varchar" for column in header]
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Generate sample data for a dbt project's sources.")
    p.add_argument("--use-case", default="enhanza-analytics")
    p.add_argument("--connector", help="only this connector's sources")
    p.add_argument("--manifest", help="manifest.json (default: <project>/target/manifest.json)")
    p.add_argument("--out", help="output directory (default: <project>/seeds/sample)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--format", choices=("text", "json"), default="text")
    args = p.parse_args(argv)

    matches = [q for q in REPO.glob(f"skill-packs/*/use-cases/{args.use_case}") if q.is_dir()]
    if not matches:
        die(f"no use-case '{args.use_case}'")
    use_case = matches[0]
    project = use_case / "dbt_project"
    manifest_path = Path(args.manifest) if args.manifest else project / "target/manifest.json"
    out_dir = Path(args.out) if args.out else project / "seeds" / "sample"

    man = Manifest.load(str(manifest_path))
    ref = Reference(use_case / "ontology" / "reference")
    seeds = build_seeds(man, ref, args.connector)

    csvs = {n: t for n, t in seeds.items() if n.endswith(".csv")}
    placeholders = sum(text.count("_value_") for text in csvs.values())
    total_rows = len(csvs) * ROWS_PER_TABLE

    if args.format == "json":
        print(json.dumps({
            "use_case": args.use_case,
            "source_tables": len(csvs),
            "rows_per_table": ROWS_PER_TABLE,
            "total_rows": total_rows,
            "placeholder_cells": placeholders,
            "out_dir": str(out_dir.relative_to(REPO)),
            "written": not args.dry_run,
        }, ensure_ascii=False))
    else:
        print(f"use-case:     {args.use_case}")
        print(f"source tables: {len(csvs)}  ({total_rows} rows at {ROWS_PER_TABLE}/table)")
        print(f"placeholder cells: {placeholders} — columns with no reference mapping")
        print(f"out:          {out_dir.relative_to(REPO)}")

    if args.dry_run:
        return 0
    if not seeds:
        print("nothing to write (no source columns resolved — is sqlglot installed?)", file=sys.stderr)
        return 3
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in seeds.items():
        (out_dir / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(seeds)} seed file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
