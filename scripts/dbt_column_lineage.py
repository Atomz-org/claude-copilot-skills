#!/usr/bin/env python3
"""Derive column-level lineage for a dbt Core project.

dbt Core computes lineage between *models* and stops there. `manifest.json` says
`erp_bi_dim_company` depends on `fortnox_erp_bi_dim_company`; nothing in it says that
`OrgName` came from `Name` two models upstream. That mapping is the one a person actually
asks for — "where does this number come from", "what breaks if I rename this column" — and
answering it needs the SQL parsed, which is why dbt Cloud sells it and dbt Core does not
ship it.

This reads `raw_code` out of the manifest rather than compiled SQL, on purpose. `dbt
compile` needs a working warehouse connection, and this project's local profile is duckdb
while its real target is BigQuery — one model using backtick-quoted
`` `db.INFORMATION_SCHEMA.TABLES` `` is enough to fail the whole compile locally. Raw code
is always present, always current with the checkout, and needs nothing but the manifest.

The cost of that choice is Jinja. `{{ ref('x') }}` and `{{ source('a','b') }}` are
substituted for identifiers; anything else becomes an opaque marker, and the columns a macro
generates are reported as `macro` rather than guessed at. Measured on enhanza-analytics:
223 of 359 models parse to real column lineage, 131 are macro-only and resolved
structurally, and 5 fail to parse and are named rather than silently dropped.

Two macro shapes are resolved structurally because their contract is definitional, not
textual:

  * `auto_config(suffix='_staging')` is `select * from ref(<model><suffix>)` — a
    pass-through, so every column maps 1:1 and the lineage is exact without parsing.
  * `erp_union()` unions `<source>_erp_bi_<concept>` across the registry, so the output
    columns are whatever the adapters agree on — which is also what makes adapter column
    drift detectable (see `scripts/connector_alignment_check.py`).

sqlglot is an optional dependency, the same shape as orjson in `scripts/_manifest.py`:
present, it parses; absent, the pass-through and union lineage still resolve and the
literal-SQL models are reported as skipped rather than the run failing.

    pip install sqlglot

Usage:
    python3 scripts/dbt_column_lineage.py --manifest <path>/target/manifest.json
    python3 scripts/dbt_column_lineage.py --manifest <path> --model fortnox_bi_dim_company
    python3 scripts/dbt_column_lineage.py --manifest <path> --column OrgName
    python3 scripts/dbt_column_lineage.py --manifest <path> --format json   # TOON-ready
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _manifest import Manifest  # noqa: E402

try:  # optional — absence degrades the run, it does not fail it
    import sqlglot
    from sqlglot import exp
except ImportError:  # pragma: no cover - depends on the environment
    sqlglot = None  # type: ignore[assignment]
    exp = None  # type: ignore[assignment]


# The dialect the project actually targets. Parsing BigQuery SQL as anything else rejects
# backtick quoting and `safe_cast`, which this project uses.
DEFAULT_DIALECT = "bigquery"

# How deep to follow a column back through chained CTEs before giving up. Nothing in a dbt
# model should need more; a cycle would otherwise spin.
MAX_CTE_DEPTH = 12

_RE_CONFIG = re.compile(r"\{\{\s*config\(.*?\)\s*\}\}", re.S)
_RE_REF = re.compile(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")
_RE_SOURCE = re.compile(
    r"\{\{\s*source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}"
)
_RE_JINJA_EXPR = re.compile(r"\{\{(.*?)\}\}", re.S)
_RE_JINJA_STMT = re.compile(r"\{%.*?%\}", re.S)
_RE_MACRO_NAME = re.compile(r"\{\{-?\s*([a-z_][a-z0-9_]*)\s*\(")

MACRO_MARKER = "JINJA_EXPR"
SOURCE_SEP = "__"


@dataclass(frozen=True)
class ColumnEdge:
    """One output column and where it came from."""

    model: str
    column: str
    upstream_model: str
    upstream_column: str
    kind: str  # direct | renamed | derived | passthrough | union | macro | unresolved

    def as_record(self) -> Dict[str, str]:
        return asdict(self)


# ---------------------------------------------------------------------------------------
# Jinja
# ---------------------------------------------------------------------------------------


_RE_JINJA_TAG = re.compile(
    r"\{%-?\s*(if|elif|else|endif|set|endset|for|endfor)\b[^%]*?-?%\}", re.S | re.I
)


def resolve_jinja_blocks(sql: str) -> str:
    """Resolve `{% if %}` and `{% set %}` blocks before the statement tags are deleted.

    Deleting `{% ... %}` tags and keeping everything between them is wrong for the two
    block forms that carry SQL, and it is wrong in a way that produces text no parser can
    accept. Both were found by running this over a real project:

      * `{% if a %} X {% else %} NULL {% endif %} as Col` collapses to `X NULL as Col`.
        Every branch survives and they concatenate. `logic_bi_fact_sales` failed exactly
        here, and `categories_x_mapping` lost the `when` of a CASE the same way, leaving a
        bare `then`.
      * `{% set q %} select ... {% endset %}` assigns SQL to a *variable*. It is not emitted
        at that position, so keeping the body splices a whole second query into the middle
        of the first.

    So: keep the first branch of a conditional, drop `set` block bodies entirely. Keeping
    the first branch rather than all of them is a real choice — the lineage reported is that
    of one branch, which is a subset of the truth and is parseable, where the concatenation
    is neither.

    This does not make the module a Jinja renderer, and it is not trying to be. A model whose
    output columns only exist after `{% set %}` variables are interpolated back in still
    cannot be read from `raw_code`; it needs `dbt compile` and a warehouse. Those are counted
    and named, never guessed at.
    """
    out: List[str] = []
    pos = 0
    keep_stack: List[bool] = []      # False once a conditional's first branch has ended
    set_depth = 0

    for match in _RE_JINJA_TAG.finditer(sql):
        tag = match.group(1).lower()
        if set_depth == 0 and all(keep_stack):
            out.append(sql[pos : match.start()])
        pos = match.end()

        if tag == "if":
            keep_stack.append(True)
        elif tag in ("elif", "else"):
            if keep_stack:
                keep_stack[-1] = False
        elif tag == "endif":
            if keep_stack:
                keep_stack.pop()
        elif tag == "set":
            # `{% set x = 1 %}` is a one-liner with no body; only the block form opens a
            # scope. The block form is the one with no `=` in the tag.
            if "=" not in match.group(0):
                set_depth += 1
        elif tag == "endset":
            set_depth = max(0, set_depth - 1)

    if set_depth == 0 and all(keep_stack):
        out.append(sql[pos:])
    return "".join(out)


def strip_jinja(sql: str, macro_form: str = MACRO_MARKER) -> str:
    """Turn a dbt model body into something a SQL parser accepts.

    `ref()` and `source()` become bare identifiers so the parser reports them as tables;
    every other Jinja expression becomes `macro_form`, which is what keeps a
    macro-generated column list from being silently read as a single column.
    """
    sql = _RE_CONFIG.sub("", sql)
    sql = resolve_jinja_blocks(sql)
    sql = _RE_REF.sub(r"\1", sql)
    sql = _RE_SOURCE.sub(rf"\1{SOURCE_SEP}\2", sql)
    sql = _RE_JINJA_EXPR.sub(macro_form, sql)
    sql = _RE_JINJA_STMT.sub("", sql)
    return sql.strip()


# A macro can expand into a fragment of any shape, and one substitution cannot be valid in
# every position it might occupy. `{{ add_erp_fields(...) }}` sits in a select list and
# expands to `, col, col`; `{{ fortnox_start_year_filter(...) }}` sits under a `where 1=1`
# and expands to `and ...`. Rather than guess the context, each candidate is tried in turn
# and the first that parses wins — a parse costs about two milliseconds, so trying four is
# cheaper than being wrong about one.
#
# The last candidate drops the macro entirely. That loses the "columns exist here that
# cannot be named" signal, so it is deliberately last: a run that reaches it reports real
# lineage for the columns that are written down and simply says nothing about the rest.
_MACRO_FORMS = (
    MACRO_MARKER,                 # bare — correct where the macro is a whole expression
    f", NULL as {MACRO_MARKER}",  # select-list item that needs its own comma
    "and TRUE",                   # boolean fragment under a WHERE
    "",                           # drop
)


def macro_calls(raw_code: str) -> List[str]:
    """Names of the macros invoked in a model body, in order of appearance."""
    return _RE_MACRO_NAME.findall(raw_code)


def has_literal_select(sql: str) -> bool:
    return bool(re.search(r"\bselect\b", sql, re.IGNORECASE))


# ---------------------------------------------------------------------------------------
# SQL walking
# ---------------------------------------------------------------------------------------


def _cte_map(tree: Any) -> Dict[str, Any]:
    with_clause = tree.find(exp.With)
    if not with_clause:
        return {}
    return {cte.alias_or_name: cte.this for cte in with_clause.expressions}


def _sources_of(select: Any) -> Tuple[Dict[str, str], List[str]]:
    """(alias -> table, ordered distinct tables) for one SELECT's own FROM and JOINs.

    Only the `from` and `joins` arguments are read. `find_all(exp.Table)` would be shorter
    and is wrong: it walks the entire subtree, so for `with main as (select ... from src)
    select OrgName from main` the outer select reports both `main` *and* `src` as its
    sources, and every unqualified column then resolves against `src` as well — inventing an
    `src.OrgName` that does not exist alongside the true `src.companyName`.
    """
    aliases: Dict[str, str] = {}
    tables: List[str] = []

    def record(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, exp.Table):
            name = node.name
            if name and name not in tables:
                tables.append(name)
            alias = node.alias
            if alias:
                aliases[alias] = name
            if name:
                aliases.setdefault(name, name)
            return
        # A derived table (`from (select ...) x`) contributes its own alias, and its
        # internals are resolved when the column is followed into it.
        if isinstance(node, exp.Subquery):
            alias = node.alias
            if alias and alias not in tables:
                tables.append(alias)
                aliases[alias] = alias

    # sqlglot 30 renamed this arg from `from` to `from_`; both spellings are accepted so a
    # version bump does not silently return "no sources" and turn every column unresolved.
    from_clause = select.args.get("from_") or select.args.get("from")
    if from_clause is not None:
        record(from_clause.this)
    for join in select.args.get("joins") or []:
        record(join.this)
    return aliases, tables


def _row_aliases(select: Any) -> Set[str]:
    """Names bound in the FROM clause that are rows, not tables.

    `from t, unnest(json_extract_array(InvoiceRows)) r` binds `r` to each unnested element.
    Later references to `r` are row variables, and reading them as columns attributes a
    column named `r` to `t` — which produced 32 edges into a `fortnox_api__v2_invoices.r`
    that does not exist. Anything bound by an UNNEST or a table-valued expression is
    collected here so those references can be dropped rather than misattributed.
    """
    out: Set[str] = set()
    from_clause = select.args.get("from_") or select.args.get("from")
    items = [from_clause.this] if from_clause is not None else []
    items += [join.this for join in select.args.get("joins") or []]
    for item in items:
        if item is None or isinstance(item, (exp.Table, exp.Subquery)):
            continue
        alias = getattr(item, "alias", None)
        if alias:
            out.add(alias)
    # BigQuery's `unnest(x) r` binds the row variable in a TableAlias's *columns* list, not
    # as the alias name — `unnest.alias` is the empty string for it. Reading only `.alias`
    # therefore finds nothing and every `r` reference is misattributed, which is exactly the
    # bug this exists to prevent, so the columns list is read explicitly.
    for unnest in select.find_all(exp.Unnest):
        if unnest.alias:
            out.add(unnest.alias)
        table_alias = unnest.args.get("alias")
        if table_alias is not None:
            for identifier in table_alias.args.get("columns") or []:
                name = getattr(identifier, "name", None)
                if name:
                    out.add(name)
        parent = unnest.parent
        if isinstance(parent, exp.Alias) and parent.alias:
            out.add(parent.alias)
    return out


def _selects_of(tree: Any) -> List[Any]:
    """Every top-level SELECT: one, or one per UNION branch."""
    union = tree.find(exp.Union)
    if union is not None:
        return [s for s in union.find_all(exp.Select) if s.find_ancestor(exp.Subquery) is None]
    select = tree.find(exp.Select)
    return [select] if select is not None else []


def _resolve(
    column: str,
    qualifier: Optional[str],
    select: Any,
    ctes: Dict[str, Any],
    depth: int = 0,
) -> List[Tuple[str, str]]:
    """Follow one column reference back to (base table, column) pairs.

    A reference into a CTE is followed into that CTE's projection list and resolved again,
    so `with s as (select Name as OrgName from src) select OrgName from s` reports
    `src.Name` rather than `s.OrgName`. An unqualified column with several candidate bases
    is ambiguous and is reported against each, because guessing one is worse than saying so.
    """
    if depth > MAX_CTE_DEPTH:
        return []
    aliases, tables = _sources_of(select)
    target = aliases.get(qualifier, qualifier) if qualifier else None
    candidates = [target] if target else tables

    out: List[Tuple[str, str]] = []
    for table in candidates:
        if table in ctes:
            inner = ctes[table]
            for inner_select in _selects_of(inner) or [inner]:
                out.extend(_resolve_projection(column, inner_select, ctes, depth + 1))
        elif table:
            out.append((table, column))
    return out


def _resolve_projection(
    name: str, select: Any, ctes: Dict[str, Any], depth: int
) -> List[Tuple[str, str]]:
    """Find `name` in a select's projections and resolve what fed it."""
    for projection in select.expressions:
        if projection.alias_or_name != name:
            continue
        return _columns_behind(projection, select, ctes, depth)
    # `select *` from a CTE: the name passes straight through.
    if any(isinstance(p, exp.Star) for p in select.expressions):
        return _resolve(name, None, select, ctes, depth + 1)
    return []


def _columns_behind(
    projection: Any, select: Any, ctes: Dict[str, Any], depth: int
) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    rows = _row_aliases(select)
    for col in projection.find_all(exp.Column):
        if col.name == MACRO_MARKER:
            continue
        # A bare reference to an UNNEST alias is a row, not a column of the base table.
        if col.name in rows and not col.table:
            continue
        if col.table and col.table in rows:
            # `r.Price` where `r` is the unnested row: the column is real but its origin is
            # the unnested expression, which this resolver does not track into. Dropping it
            # is honest; attributing it to the base table is not.
            continue
        out.extend(_resolve(col.name, col.table or None, select, ctes, depth))
    return out


def _absorbed_a_column(tree: Any) -> bool:
    """True when the macro marker swallowed the projection in front of it.

    `select OrgId, City\\n  {{ macro }}\\nfrom t` becomes `select OrgId, City JINJA_EXPR
    from t`, and SQL reads a bare identifier after an expression as an alias — so it parses
    cleanly as `City AS JINJA_EXPR` and `City` disappears from the output columns. A
    successful parse is therefore not enough; the result has to be checked for this, or the
    fallback chain stops at a form that is syntactically valid and semantically wrong.
    """
    for select in tree.find_all(exp.Select):
        for projection in select.expressions:
            if projection.alias_or_name != MACRO_MARKER:
                continue
            # The marker standing on its own parses *as* a column named JINJA_EXPR, which is
            # correct and must not be read as absorption — only a column with some *other*
            # name underneath it means a real projection was swallowed.
            if any(c.name != MACRO_MARKER for c in projection.find_all(exp.Column)):
                return True
    return False


# How many macro occurrences the per-occurrence fallback will try combinations for.
# Cost is len(_MACRO_FORMS) ** n parses at roughly 2 ms each, so 4 occurrences is ~0.5 s and
# 5 would be ~2 s. The fallback only runs for a model no uniform form could parse — one in
# 361 here — so a bound this low costs nothing and cannot turn into a hang.
MAX_MIXED_MACROS = 4


def _substitute_per_occurrence(sql: str, forms: Sequence[str]) -> str:
    """Replace the i-th `{{ ... }}` with `forms[i]`."""
    index = 0

    def swap(_match: Any) -> str:
        nonlocal index
        form = forms[index] if index < len(forms) else MACRO_MARKER
        index += 1
        return form

    return _RE_JINJA_EXPR.sub(swap, sql)


def parse_model_sql(raw_code: str, dialect: str) -> Tuple[Any, Optional[str]]:
    """Parse a dbt model body, trying each macro substitution until one succeeds.

    Two passes. The uniform pass applies one substitution to every macro in the model and
    handles all but a handful; the mixed pass exists because a model can hold macros in
    *different* syntactic positions at once, and then no single substitution is valid
    anywhere. `logic_bi_dim_articles` is the case that forced it: one macro sits in the
    select list and needs `, NULL as X`, another sits after the FROM and needs a boolean —
    the uniform pass fails all four forms and reported the model as unparseable when its
    column list was perfectly readable.

    The mixed pass is a fallback, not the default, because it is exponential in the number
    of macros and the uniform pass already answers for 224 of 225 models here.
    """
    first_error: Optional[str] = None

    def attempt(sql: str) -> Optional[Any]:
        nonlocal first_error
        if not has_literal_select(sql):
            return None
        try:
            tree = sqlglot.parse_one(sql, dialect=dialect)
        except Exception as exc:  # sqlglot raises several types; none are actionable here
            if first_error is None:
                first_error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:120]}"
            return None
        if tree is not None and not _absorbed_a_column(tree):
            return tree
        return None

    for form in _MACRO_FORMS:
        tree = attempt(strip_jinja(raw_code, form))
        if tree is not None:
            return tree, None

    prepared = _RE_JINJA_STMT.sub(
        "", _RE_SOURCE.sub(rf"\1{SOURCE_SEP}\2", _RE_REF.sub(
            r"\1", resolve_jinja_blocks(_RE_CONFIG.sub("", raw_code))
        ))
    )
    occurrences = len(_RE_JINJA_EXPR.findall(prepared))
    if 1 < occurrences <= MAX_MIXED_MACROS:
        import itertools

        for combination in itertools.product(_MACRO_FORMS, repeat=occurrences):
            if len(set(combination)) == 1:
                continue  # already covered by the uniform pass
            tree = attempt(_substitute_per_occurrence(prepared, combination).strip())
            if tree is not None:
                return tree, None

    return None, first_error or "empty parse"


def lineage_from_sql(model_name: str, raw_code: str, dialect: str) -> Tuple[List[ColumnEdge], Optional[str]]:
    """Column edges for one model body. Returns (edges, error)."""
    tree, error = parse_model_sql(raw_code, dialect)
    if error:
        return [], error

    ctes = _cte_map(tree)
    edges: List[ColumnEdge] = []
    selects = _selects_of(tree)
    is_union = tree.find(exp.Union) is not None

    for select in selects:
        _, tables = _sources_of(select)
        bases = [t for t in tables if t not in ctes]
        for projection in select.expressions:
            if isinstance(projection, exp.Star):
                for base in bases:
                    edges.append(ColumnEdge(model_name, "*", base, "*", "passthrough"))
                continue
            alias = projection.alias_or_name
            if alias == MACRO_MARKER or not alias:
                # A macro expanded into an unknown number of columns. Recording the fact is
                # honest; inventing the names it generates would not be.
                for base in bases:
                    edges.append(ColumnEdge(model_name, "(macro)", base, "(macro)", "macro"))
                continue
            behind = _columns_behind(projection, select, ctes, 0)
            if not behind:
                edges.append(ColumnEdge(model_name, alias, "", "", "unresolved"))
                continue
            # A function or a multi-column expression is a transform regardless of what the
            # output is called. `initcap(City) as City` keeps its name and is still derived;
            # classifying it `direct` because the names match would say the value passed
            # through untouched, which is the opposite of true. `cast` counts — it is an
            # exp.Func subclass, and a cast is a transform.
            transformed = bool(list(projection.find_all(exp.Func))) or len(behind) > 1
            for upstream_model, upstream_column in behind:
                if is_union:
                    kind = "union"
                elif transformed:
                    kind = "derived"
                elif upstream_column == alias:
                    kind = "direct"
                else:
                    kind = "renamed"
                edges.append(
                    ColumnEdge(model_name, alias, upstream_model, upstream_column, kind)
                )
    return _dedupe(edges), None


def _dedupe(edges: Iterable[ColumnEdge]) -> List[ColumnEdge]:
    seen: Set[ColumnEdge] = set()
    out: List[ColumnEdge] = []
    for edge in edges:
        if edge in seen:
            continue
        seen.add(edge)
        out.append(edge)
    return out


# ---------------------------------------------------------------------------------------
# Macro-only models
# ---------------------------------------------------------------------------------------


def structural_lineage(node: Dict[str, Any], by_name: Dict[str, Dict[str, Any]]) -> List[ColumnEdge]:
    """Lineage for a model whose body is a project macro rather than SQL.

    Only the two macros whose contract is definitional are resolved. Anything else returns
    nothing and is counted as macro-only, rather than being approximated.
    """
    name = node.get("name", "")
    raw = node.get("raw_code") or ""
    calls = macro_calls(raw)
    parents = [
        by_name[p]["name"]
        for p in node.get("depends_on", {}).get("nodes", []) or []
        if p in by_name
    ]

    if "auto_config" in calls:
        # `select * from ref(model.name + suffix)`; the suffix defaults to `_staging` and is
        # overridable, so the parent list is trusted over reconstructing the name.
        suffix_match = re.search(r"auto_config\(\s*suffix\s*=\s*['\"]([^'\"]*)['\"]", raw)
        expected = f"{name}{suffix_match.group(1) if suffix_match else '_staging'}"
        target = expected if expected in [p for p in parents] else (parents[0] if parents else "")
        if target:
            return [ColumnEdge(name, "*", target, "*", "passthrough")]
        return []

    if any(call in ("erp_union", "configure_erp") for call in calls):
        return [ColumnEdge(name, "*", parent, "*", "union") for parent in parents]

    return []


# ---------------------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------------------


def build_lineage(man: Manifest, dialect: str = DEFAULT_DIALECT) -> Dict[str, Any]:
    by_id = {
        uid: node
        for uid, node in man.nodes.items()
        if node.get("resource_type") == "model"
    }
    by_name = {node["name"]: node for node in by_id.values()}

    edges: List[ColumnEdge] = []
    parsed = macro_only = failed = no_parser = 0
    failures: List[Dict[str, str]] = []

    for node in by_id.values():
        name = node.get("name", "")
        raw = node.get("raw_code") or ""
        sql = strip_jinja(raw)
        if not has_literal_select(sql):
            structural = structural_lineage(node, by_name)
            edges.extend(structural)
            macro_only += 1
            continue
        if sqlglot is None:
            # Counted, not skipped silently. Every model has to land in exactly one bucket
            # or the coverage line understates the project and reads as if the models were
            # simply absent.
            no_parser += 1
            continue
        model_edges, error = lineage_from_sql(name, raw, dialect)
        if error:
            failed += 1
            failures.append({"model": name, "error": error})
            continue
        parsed += 1
        edges.extend(model_edges)

    return {
        "models": len(by_id),
        "parsed": parsed,
        "macro_only": macro_only,
        "parse_failed": failed,
        "no_parser": no_parser,
        "sqlglot": bool(sqlglot),
        "edges": edges,
        "failures": failures,
    }


def adapter_column_sets(
    man: Manifest, lineage: Dict[str, Any]
) -> Dict[str, Dict[str, Set[str]]]:
    """`{concept: {source: {columns}}}` for every `<source>_erp_bi_<concept>` adapter.

    This is what makes UNION column drift visible without a warehouse. `erp_union()` stacks
    one adapter per enabled source, so a new connector whose adapter omits a column the
    others carry produces a union that only fails when both are enabled at once — the case
    a single-connector build never reaches.
    """
    columns: Dict[str, Dict[str, Set[str]]] = {}
    by_model: Dict[str, Set[str]] = {}
    for edge in lineage["edges"]:
        if edge.column not in ("*", "(macro)"):
            by_model.setdefault(edge.model, set()).add(edge.column)

    pattern = re.compile(r"^([a-z_0-9]+?)_erp_bi_(.+)$")
    for node in man.nodes.values():
        if node.get("resource_type") != "model":
            continue
        match = pattern.match(node.get("name", ""))
        if not match:
            continue
        source, concept = match.group(1), match.group(2)
        cols = by_model.get(node["name"])
        if cols:
            columns.setdefault(concept, {})[source] = cols
    return columns


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Derive column-level lineage from a dbt manifest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--manifest", required=True, help="path to manifest.json")
    p.add_argument("--model", help="only this model's columns")
    p.add_argument("--column", help="only columns with this name (case-insensitive)")
    p.add_argument("--upstream-of", help="trace what feeds this model")
    p.add_argument("--dialect", default=DEFAULT_DIALECT, help=f"sqlglot dialect (default: {DEFAULT_DIALECT})")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.add_argument("--limit", type=int, default=40, help="max rows in text mode")
    args = p.parse_args(argv)

    man = Manifest.load(str(args.manifest))
    lineage = build_lineage(man, args.dialect)
    edges: List[ColumnEdge] = lineage["edges"]

    if args.model:
        edges = [e for e in edges if e.model == args.model]
    if args.upstream_of:
        edges = [e for e in edges if e.model == args.upstream_of]
    if args.column:
        needle = args.column.lower()
        edges = [e for e in edges if needle in (e.column.lower(), e.upstream_column.lower())]

    if args.format == "json":
        print(json.dumps({
            "project": man.project_name,
            "models": lineage["models"],
            "models_parsed": lineage["parsed"],
            "models_macro_only": lineage["macro_only"],
            "models_parse_failed": lineage["parse_failed"],
            "models_no_parser": lineage["no_parser"],
            "sqlglot_available": lineage["sqlglot"],
            "column_edges": len(edges),
            "lineage": [e.as_record() for e in edges[:args.limit]],
            "truncated": max(0, len(edges) - args.limit),
        }, ensure_ascii=False))
        return 0

    print(f"project: {man.project_name}")
    if not lineage["sqlglot"]:
        print("sqlglot: NOT INSTALLED — only pass-through and union lineage resolved.")
        print("         pip install sqlglot   for column-level lineage through SQL.")
    print(
        f"models:  {lineage['models']} total · {lineage['parsed']} parsed · "
        f"{lineage['macro_only']} macro-only · {lineage['parse_failed']} parse-failed"
        + (f" · {lineage['no_parser']} needing sqlglot" if lineage['no_parser'] else "")
    )
    print(f"columns: {len(edges)} lineage edges")
    print()
    for edge in edges[:args.limit]:
        upstream = f"{edge.upstream_model}.{edge.upstream_column}" if edge.upstream_model else "(unresolved)"
        print(f"  {f'{edge.model}.{edge.column}':<58} <- {upstream:<56} [{edge.kind}]")
    if len(edges) > args.limit:
        print(f"  ... {len(edges) - args.limit} more (raise --limit)")
    if lineage["failures"]:
        print()
        print(f"{len(lineage['failures'])} model(s) did not parse:")
        for failure in lineage["failures"][:5]:
            print(f"  {failure['model']}: {failure['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
