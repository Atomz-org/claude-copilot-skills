#!/usr/bin/env python3
"""Rewrite a `select *` into the explicit column list its upstream declares.

`no_star_check.py` refuses a star that reaches a model's output schema and records the
existing ones as a baseline. This is what works that baseline down, and it does it from
committed artifacts alone — no warehouse, no `dbt docs generate`, no guessing.

Where the columns come from
---------------------------

`select * from {{ source('a', 'b') }}` expands to the columns that source **declares**.
That is not a compromise, it is the definition this repository already uses: a source
contract is *"a statement of what this project depends on, not an inventory of what the
API returns"*. Expanding to the contract makes the staging model read exactly what has
been declared — and `check_source_columns` already fails a staging model that reads a
column its source does not declare, so the two agree by construction.

`select * from {{ ref('m') }}` expands to whatever `m` outputs, resolved by iterating to a
fixpoint rather than by parsing SQL: a model whose own star this tool expanded now has a
known column list, so the models above it become resolvable on the next pass. Nothing is
inferred from a query plan, so nothing can be inferred wrongly.

`{{ add_erp_fields(columns=[...]) }}` is computed, not skipped. `column-memory.json` marks
ten of these models `partial` because its sqlglot pass cannot see through a macro, but the
macro is deterministic: it emits `DataSource`, `DefaultCurrency`, and one `<Col>ERP` alias
per argument column ending in `Id` that is not in `global_configs('id_erp_exceptions')`.
Reading the macro and the exception list names every one of them exactly.

What it refuses
---------------

- **A model with more than one star.** Five of the sixty have several, in branches of a
  union or a pivot. Which star owns which output column is a question the fixpoint cannot
  answer, and rewriting the wrong one silently changes the model's shape.
- **An upstream that declares nothing.** A source with no `columns:` block, or a `ref()`
  whose target this tool has not resolved. Reported and left alone — expanding to an empty
  list would delete the model's output.
- **Anything not in the baseline.** New stars are the gate's job, not this tool's.

Ordering is preserved as declared, because these models feed positional unions
(`erp_union()` stacks one adapter per enabled source) and a reordered projection breaks
the union in a way no test here would catch.

Usage:
    python3 scripts/expand_star_models.py --use-case <slug>            # dry run
    python3 scripts/expand_star_models.py --use-case <slug> --write
    python3 scripts/expand_star_models.py --use-case <slug> --model <name>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _paths  # noqa: E402
import dbt_column_lineage as dcl  # noqa: E402
import no_star_check as ns  # noqa: E402

from sqlglot import expressions as sqlglot_exp  # noqa: E402

DIALECT = dcl.DEFAULT_DIALECT

REPO = _paths.REPO

SOURCE_CALL = re.compile(r"\bsource\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]")
REF_CALL = re.compile(r"\bref\s*\(\s*['\"]([^'\"]+)['\"]")
ERP_FIELDS = re.compile(r"add_erp_fields\s*\(\s*columns\s*=\s*\[([^\]]*)\]", re.S)
# One definition of "a select whose projection is a star", used by the detector in
# `load_models` and by `rewrite`. It was two — the detector matched `select distinct *` and
# this did not — and the disagreement was silent in the worst direction: `load_models`
# admitted such a model, `resolve` derived its columns, `run` recorded it as expanded, and
# `rewrite` found no match and returned the file untouched. The report said the star was
# gone, the file still had it, and `no_star_check` still flagged it. Group 1 carries the
# `distinct` so the rewrite cannot drop it.
STAR = re.compile(r"(\bselect\s+(?:distinct\s+)?)(\*)", re.I)

# `target/` and `target-sample/` hold dbt's compiled copy of a model that also lives under
# `models/`, and `dbt_packages/` holds the installed copy of a local package's models — so
# a bare `rglob("<ref>.sql")` returns the same model two or three times and the first hit
# is filesystem order. Measured on enhanza-analytics: **394 of 707 stems duplicate, every
# duplicate a build artifact, and rglob returned the compiled copy first.** Both trees are
# gitignored, so the tool read a stale compiled artifact on a developer machine and the
# source model on a fresh clone — one input, two answers, neither announced.
#
# A deliberate *subset* of `no_star_check.EXCLUDED_DIRS`. That list also drops `snapshots/`,
# `macros/`, `tests/` and `analyses/`, which is right for "where may a star live" and wrong
# for "what may a ref resolve to": `ref('<snapshot>')` is legal dbt. The subset relationship
# is pinned by a test rather than by an assert here.
BUILD_DIRS = ("target", "target-sample", "dbt_packages")


def use_case_dir(slug: str) -> Path:
    return _paths.require_use_case_dir(slug, REPO)


# ---------------------------------------------------------------------------------------
# What the project declares
# ---------------------------------------------------------------------------------------


def declared_source_columns(project: Path) -> Dict[Tuple[str, str], List[str]]:
    """{(source, table): [column, ...]} from every sources.yml.

    Keyed by the pair, never by table alone: two sources.yml here declare three and five
    sources, and nothing stops two of them exposing a `customers`. It does not collide
    today and is one added table away from writing one source's columns under another's.
    """
    out: Dict[Tuple[str, str], List[str]] = {}
    for path in sorted(project.rglob("sources.yml")):
        source: Optional[str] = None
        table: Optional[str] = None
        in_columns = False
        for line in path.read_text(encoding="utf-8").splitlines():
            source_match = re.match(r"^  - name:\s*(\S+)", line)
            if source_match:
                source, table, in_columns = source_match.group(1), None, False
                continue
            table_match = re.match(r"^      - name:\s*(\S+)", line)
            if table_match:
                table, in_columns = table_match.group(1), False
                continue
            if re.match(r"^        columns:\s*$", line):
                in_columns = True
                continue
            if in_columns:
                column_match = re.match(r"^          - name:\s*(\S+)", line)
                if column_match and source and table:
                    out.setdefault((source, table), []).append(column_match.group(1))
                elif re.match(r"^        \S", line) or re.match(r"^      \S", line):
                    in_columns = False
    return out


def erp_exceptions(project: Path) -> set:
    """`id_erp_exceptions` — the columns the macro does NOT give an `<Col>ERP` alias."""
    macro = project / "macros/config/global_configs.sql"
    if not macro.exists():
        return set()
    text = macro.read_text(encoding="utf-8")
    block = re.search(r"'id_erp_exceptions':\s*\[(.*?)\]", text, re.S)
    if not block:
        return set()
    names = re.findall(r"'([^']+)'", block.group(1))
    # The first entry is the list's own description, not a column.
    return {n for n in names if " " not in n}


def erp_macro_columns(sql: str, exceptions: set) -> List[str]:
    """Exactly what `add_erp_fields(columns=[...])` adds, in the order the macro emits."""
    match = ERP_FIELDS.search(sql)
    if not match:
        return []
    arguments = re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))
    out = ["DataSource", "DefaultCurrency"]
    out += [f"{c}ERP" for c in arguments if c.endswith("Id") and c not in exceptions]
    return out


# ---------------------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------------------


@dataclass
class Model:
    rel: str
    path: Path
    name: str
    sql: str
    star_count: int
    star_pos: int = -1
    # The relation the star's OWN select reads from. Not "a source mentioned anywhere in
    # the file": these models routinely wrap a source in a CTE and select from the CTE, so
    # attributing the source's columns to the outer select names columns that do not exist
    # there. That is the defect CLAUDE.md records for `find_all(exp.Table)` — "an outer
    # SELECT claimed its CTE's base table as its own source" — and it was reproduced here
    # by the first version of this tool.
    source: Optional[Tuple[str, str]] = None
    ref: Optional[str] = None
    cte: Optional[str] = None
    macro_columns: List[str] = field(default_factory=list)
    # What replaces the `*`: the upstream's columns, and only those. The macro emits its
    # own columns at its own call site, so including them here printed every `<Col>ERP`
    # twice.
    star_columns: Optional[List[str]] = None
    reason: str = ""

    @property
    def output_columns(self) -> Optional[List[str]]:
        """What this model publishes — the star's columns plus whatever the macro adds.

        Distinct from `star_columns`, and the distinction is load-bearing: this is what a
        downstream `select * from ref(this)` must expand to, while `star_columns` is only
        the text that replaces this model's own star.
        """
        if self.star_columns is None:
            return None
        return list(self.star_columns) + self.macro_columns


def star_from_clause(sql: str, body: str, star_pos: int) -> Optional[str]:
    """The text of the `from` belonging to the star's own select.

    `strip_noise` replaces comments and Jinja with equal-length whitespace, so offsets in
    `body` index `sql` exactly — depth is computed on the stripped copy (where Jinja
    parentheses cannot skew it) and the text is read from the original (where the
    `{{ source(...) }}` call survives).
    """
    depth = ns._depth_at(body, star_pos)
    for match in re.finditer(r"(?i)\bfrom\b", body[star_pos:]):
        position = star_pos + match.start()
        if ns._depth_at(body, position) == depth:
            return sql[position:position + 300]
    return None


def load_models(project: Path, baseline: List[str], exceptions: set) -> Dict[str, Model]:
    models: Dict[str, Model] = {}
    for rel in baseline:
        path = project / rel
        if not path.exists():
            continue
        sql = path.read_text(encoding="utf-8", errors="replace")
        body = ns.strip_noise(sql)
        stars = list(STAR.finditer(body))
        model = Model(rel=rel, path=path, name=path.stem, sql=sql,
                      star_count=len(stars),
                      macro_columns=erp_macro_columns(sql, exceptions))
        if len(stars) == 1:
            model.star_pos = stars[0].start()
            clause = star_from_clause(sql, body, model.star_pos)
            if clause:
                source = SOURCE_CALL.search(clause)
                ref = REF_CALL.search(clause)
                if source:
                    model.source = (source.group(1), source.group(2))
                elif ref:
                    model.ref = ref.group(1)
                else:
                    bare = re.match(r"(?is)\bfrom\b\s+([A-Za-z_]\w*)", clause)
                    model.cte = bare.group(1) if bare else None
        models[path.stem] = model
    return models


def output_columns_of_explicit_model(path: Path) -> Optional[List[str]]:
    """The columns a model projects, read with the parser that already exists here.

    `dbt_column_lineage.parse_model_sql` is the repository's Jinja-aware sqlglot pass —
    it resolves `{% if %}` branches, drops `{% set %}` bodies, and substitutes macro
    markers, all behaviours pinned by `tests/test_dbt_column_lineage.py`. A regex reader
    was tried first and could not read 26 of these projections, which would have made the
    tool a no-op; reimplementing the parse instead of importing it would have
    reintroduced every bug that file already records.

    Returns None where the projection still carries a star, because then the answer
    depends on a relation this function has not resolved.
    """
    try:
        tree, error = dcl.parse_model_sql(path.read_text(encoding="utf-8", errors="replace"),
                                          DIALECT)
    except Exception:  # noqa: BLE001 - a parse failure is a refusal, never a crash
        return None
    if tree is None or error:
        return None
    select = tree if isinstance(tree, sqlglot_exp.Select) else None
    if select is None:
        selects = dcl._selects_of(tree)
        if not selects:
            return None
        select = selects[-1]
    columns: List[str] = []
    for expression in select.expressions:
        if isinstance(expression, sqlglot_exp.Star) or "*" in expression.sql():
            return None
        name = expression.alias_or_name
        if not name:
            return None
        columns.append(name)
    return columns or None


def resolve(models: Dict[str, Model], sources: Dict[Tuple[str, str], List[str]],
            project: Path) -> None:
    """Fixpoint: source-backed models first, then whatever their consumers need."""
    for model in models.values():
        if model.star_count != 1:
            model.reason = f"{model.star_count} stars — which one owns the output is ambiguous"
            continue
        if model.cte:
            # The star reads from a CTE defined in this file. Expanding it needs that
            # CTE's projection, which is a different problem from resolving an upstream
            # model, and getting it wrong names columns the CTE does not produce.
            model.reason = (f"the star reads from CTE `{model.cte}`, not from a source or "
                            "ref — its projection is not resolvable here")
            continue
        if model.source:
            declared = sources.get(model.source)
            if not declared:
                model.reason = (f"source {model.source[0]}.{model.source[1]} declares no "
                                "columns: — nothing to expand to")
                continue
            model.star_columns = list(declared)

    for _ in range(10):
        progressed = False
        for model in models.values():
            if model.star_columns is not None or model.reason or not model.ref:
                continue
            upstream = models.get(model.ref)
            if upstream is not None:
                if upstream.output_columns is None:
                    continue
                # The upstream's OUTPUT, macro columns included — that is what a
                # `select *` over it actually returns.
                model.star_columns = list(upstream.output_columns)
                progressed = True
                continue
            candidates = sorted(
                p for p in project.rglob(f"{model.ref}.sql")
                if not set(p.relative_to(project).parts) & set(BUILD_DIRS))
            if not candidates:
                model.reason = f"ref('{model.ref}') resolves to no model file"
                continue
            if len(candidates) > 1:
                # Two real model files answering to one name is a project defect this tool
                # cannot adjudicate, and picking the first is how it would rewrite a model
                # against the wrong contract while reading as resolved. Measured: zero
                # today, which is what makes refusing cheap.
                where = ", ".join(str(p.relative_to(project)) for p in candidates[:3])
                model.reason = (
                    f"ref('{model.ref}') resolves to {len(candidates)} model files "
                    f"({where}{', ...' if len(candidates) > 3 else ''}) — which one it "
                    "means is ambiguous")
                continue
            columns = output_columns_of_explicit_model(candidates[0])
            if columns is None:
                model.reason = (f"ref('{model.ref}') projects a list this tool cannot read "
                                "cleanly — left alone rather than half-read")
                continue
            model.star_columns = columns
            progressed = True
        if not progressed:
            break

    for model in models.values():
        if model.star_columns is None and not model.reason:
            model.reason = "upstream unresolved after fixpoint"


# ---------------------------------------------------------------------------------------
# Rewrite
# ---------------------------------------------------------------------------------------


def rewrite(model: Model) -> Optional[str]:
    """Replace this model's single star with its upstream's column list, or None.

    Only the star. `add_erp_fields` emits its own columns at its own call site, so listing
    them here too printed every `<Col>ERP` twice — found by reading the first rewrite.
    The banner goes immediately above the select that owns the star, not above the first
    select in the file, which is usually inside a CTE.

    Matched on the **stripped** body and anchored at `star_pos`, never re-searched on the
    raw SQL. `load_models` detects the star on `strip_noise(sql)`, so anything that pass
    blanks — a comment or a Jinja tag between the keyword and the star — makes the raw text
    unmatchable while the detector is perfectly happy. That is not hypothetical: the house
    staging stub is

        select
            -- RawColumnName as ColumnName
            *

    and all four of this project's expandable models carry it. Re-searching the raw SQL
    found nothing, `rewrite` returned the file unchanged, and `run` had already recorded it
    as expanded — so `--write` reported four expansions and wrote four identical files,
    with `no_star_check` still flagging every one.

    `strip_noise` is length-preserving, so a span found in the body indexes `sql` exactly;
    the prefix is then read back out of `sql` and a `distinct` or a comment survives
    verbatim. A star that does not match where it was found returns None, and the caller
    refuses it rather than reporting a no-op as an expansion.
    """
    assert model.star_columns is not None
    match = STAR.match(ns.strip_noise(model.sql), max(model.star_pos, 0))
    if match is None:
        return None
    indent = "    "
    listing = indent + f"\n{indent}, ".join(model.star_columns)
    banner = (
        "-- Columns enumerated by scripts/expand_star_models.py from the upstream's own\n"
        "-- declaration; `select *` gave this model no column contract. Regenerate after\n"
        "-- changing the upstream contract; do not hand-edit the list.\n"
    )
    line_start = model.sql.rfind("\n", 0, match.start()) + 1
    return (
        model.sql[:line_start] + banner
        + model.sql[line_start:match.start()]
        + model.sql[match.start(1):match.end(1)] + "\n" + listing
        + model.sql[match.end():]
    )


def run(slug: str, write: bool, only: Optional[str],
        exclude: Optional[str] = None) -> Dict[str, Any]:
    use_case = use_case_dir(slug)
    project = use_case / "dbt_project"
    baseline_path = use_case / "artifacts" / ns.BASELINE_NAME
    if not baseline_path.exists():
        return {"status": "skip", "reason": f"no {baseline_path.relative_to(REPO)}"}
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")).get("models") or []

    exceptions = erp_exceptions(project)
    sources = declared_source_columns(project)
    models = load_models(project, baseline, exceptions)
    resolve(models, sources, project)

    expanded: List[Dict[str, Any]] = []
    refused: List[Dict[str, str]] = []
    for name in sorted(models):
        model = models[name]
        if only and name != only:
            continue
        if exclude and re.search(exclude, model.rel):
            # A held decision, not a failure to resolve: the columns are derivable and
            # somebody has chosen to wait for the real schema before committing to them.
            refused.append({"model": model.rel, "reason": f"excluded by --exclude {exclude!r}"})
            continue
        if model.star_columns is None:
            refused.append({"model": model.rel, "reason": model.reason})
            continue
        # Rewritten in dry run too, and reported on the result. Recording "expandable" off
        # the resolved columns alone said a model would be rewritten that `--write` then
        # left untouched — the run reported the star gone while `no_star_check` still
        # flagged it, and the quiet detector is the one people read.
        rewritten = rewrite(model)
        if rewritten is None:
            refused.append({"model": model.rel, "reason": (
                "columns resolved, but the star's own `select` does not match where it was "
                "found — left alone rather than reported as expanded")})
            continue
        expanded.append({"model": model.rel, "columns": len(model.star_columns),
                         "macro_columns": len(model.macro_columns),
                         "names": model.star_columns})
        if write:
            model.path.write_text(rewritten, encoding="utf-8")

    return {
        "status": "ok",
        "use_case": slug,
        "baselined": len(baseline),
        "expandable": len(expanded),
        "refused": len(refused),
        "declared_sources": len(sources),
        "expanded": expanded,
        "refusals": refused,
        "written": write,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--use-case", required=True)
    parser.add_argument("--model", help="expand only this model")
    parser.add_argument("--write", action="store_true", help="rewrite the model files")
    parser.add_argument("--exclude", help="regex of model paths to leave alone")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    payload = run(args.use_case, args.write, args.model, args.exclude)
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    if payload["status"] == "skip":
        print(f"skip: {payload['reason']}")
        return 0

    print(f"{payload['baselined']} baselined model(s); "
          f"{payload['expandable']} expandable, {payload['refused']} refused")
    for entry in payload["expanded"][:60]:
        macro = f" (+{entry['macro_columns']} from add_erp_fields)" if entry["macro_columns"] else ""
        print(f"  {entry['model']}: {entry['columns']} column(s){macro}")
    for refusal in payload["refusals"]:
        print(f"  [refused] {refusal['model']}: {refusal['reason']}")
    print(f"\n{'rewrote' if payload['written'] else 'dry run — nothing written'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
