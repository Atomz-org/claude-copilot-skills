#!/usr/bin/env python3
"""Derive a raw source's column list from published connector schemas, with citations.

Every generator in this repository stops at the same wall: `sources.yml` declares which
tables exist and nothing says which *columns* they carry, so a staging model over an
un-landed source has nothing to enumerate and falls back to `select *`. Rule 5 forbids
inventing the names, and it is right — an invented column list reads as a verified
contract and generates the very tests that would have caught it being wrong.

But "unknown to this repository" is not the same as "unknown". A connector's raw schema
is *published*, by the people who built the connector:

    fivetran/dbt_<name>_source   models/src_<name>.yml   raw tables + columns + descriptions
    dlt-hub/verified-sources     sources/<name>/         the properties the source requests

So the column list is derived from a cited artifact rather than recalled, and it stays a
**proposal** until a human confirms it — the same shape as `lm_propose.py`, for the same
reason. The confirmation route is OpenMetadata: a steward checks the derived list against
the catalog once the data lands, and `openmetadata_feedback.py --propose` carries any
correction back.

What makes a derived column trustworthy
---------------------------------------

1. **A citation or nothing.** Every column carries the repository, ref, file, and the
   identifier it was read from. A column the references do not mention is not emitted —
   there is no "probably has an email field" path, because that is the invention rule 5
   forbids wearing a citation's clothes.
2. **The network is a separate act.** `--refresh` fetches and writes
   `references/connector-schemas/<name>.json`; everything else reads that committed file.
   A generator that fetched at run time would make its output differ between machines and
   `--check` permanently red — the same rule that keeps the dlt warehouse behind
   `--with-warehouse`.
3. **Table matching is reported, never silent.** Our `companies` and Fivetran's `company`
   are the same table under two conventions, and `contacts`/`contact` likewise — but
   `account_details` matches nothing Fivetran publishes, and saying so is the useful
   output. Every match records how it was made; every miss is listed.
4. **Nothing is promoted automatically.** `--write` puts the proposal in
   `ontology/proposals/source-columns.derived.yml`. Promoting into `sources.yml` is
   `--promote`, which refuses any table that already declares `columns:` — the generated
   list bootstraps a contract a human then owns.

Usage:
    python3 scripts/source_schema_derive.py --connector hubspot --refresh     # network
    python3 scripts/source_schema_derive.py --use-case <slug> --source hubspot_api
    python3 scripts/source_schema_derive.py --use-case <slug> --source hubspot_api --write
    python3 scripts/source_schema_derive.py --use-case <slug> --source hubspot_api --promote
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _miniyaml  # noqa: E402
import _paths  # noqa: E402

REPO = _paths.REPO
CACHE_DIR = REPO / "references" / "connector-schemas"
PROPOSAL_NAME = "source-columns.derived.yml"

GENERATED_BANNER = "# generated: source_schema_derive"

# Load-bookkeeping columns belonging to the *reference* connector, not to this project.
# Fivetran stamps `_fivetran_synced` / `_fivetran_deleted` on every table it lands; this
# project ingests with dlt and gets `_dlt_id` / `_dlt_load_id` instead. Copying them
# across would declare a contract on columns that will never exist here, and
# `check_source_columns` would then fail every staging model that correctly ignores them.
# Dropped rather than renamed: which dlt column corresponds to which is a mapping nobody
# has established.
VENDOR_LOAD_COLUMNS = re.compile(r"^_(fivetran|airbyte|stitch|meltano)_", re.I)

# Fivetran's schema files describe most columns with `{{ doc('...') }}`, resolved against
# doc blocks in *their* package. Carried across verbatim they reference blocks this
# project does not define and `dbt parse` fails outright — found by promoting them and
# running it. The column still lands; only the unresolvable description is dropped.
DOC_REFERENCE = re.compile(r"\{\{\s*doc\s*\(")


@dataclass(frozen=True)
class Reference:
    """One published schema, how to cite it, and whose naming convention it lands.

    `loader` is the field that stops two references being unioned into a contract that
    matches no real warehouse. Fivetran's HubSpot `contact` table has `property_email`;
    dlt's has `email` — the same field under two ingestion tools, and a warehouse has one
    or the other. Merging them declares a table with both, so `check_source_columns` would
    then fail every staging model, correctly, for not reading a column that does not exist.

    Found by running it: the first derivation produced `['property_email', ..., 'email']`
    on one table. The evidence that settles which applies is in the project itself — every
    other source here declares PascalCase API field names (`OrgId`, `CauseCode`) and no
    model anywhere reads a `property_`-prefixed column, so this project does not land the
    Fivetran shape.
    """

    kind: str
    url: str
    cite: str
    loader: str
    # Lower sorts first. The preferred reference supplies the contract; the others are
    # recorded as cross-references, so the wider inventory stays visible without being
    # asserted as this project's column names.
    rank: int = 100


# The reference set the user named, resolved to the specific files that actually carry a
# raw-layer column list. `awesome-dbt` is an index of packages rather than a schema, so it
# is where a new entry here comes *from*, not something parsed.
#
# dlt ranks above Fivetran for every connector here because this repository ingests with
# dlt — `openmetadata_sync.py` tags `_dlt_id`/`_dlt_load_id` as its load columns, and no
# model reads a `property_`-prefixed one. On a project that landed Fivetran tables the
# ranks would be the other way round, which is why this is data rather than a hardcoded
# preference.
REFERENCES: Dict[str, Tuple[Reference, ...]] = {
    "hubspot": (
        Reference(
            kind="dlt_settings_py", loader="dlt", rank=10,
            url="https://raw.githubusercontent.com/dlt-hub/verified-sources/master/sources/hubspot/settings.py",
            cite="dlt-hub/verified-sources@master sources/hubspot/settings.py",
        ),
        Reference(
            kind="fivetran_src_yml", loader="fivetran", rank=20,
            url="https://raw.githubusercontent.com/fivetran/dbt_hubspot_source/main/models/src_hubspot.yml",
            cite="fivetran/dbt_hubspot_source@main models/src_hubspot.yml",
        ),
    ),
    "shopify": (
        Reference(
            kind="fivetran_src_yml", loader="fivetran", rank=20,
            url="https://raw.githubusercontent.com/fivetran/dbt_shopify_source/main/models/src_shopify.yml",
            cite="fivetran/dbt_shopify_source@main models/src_shopify.yml",
        ),
    ),
    "salesforce": (
        Reference(
            kind="fivetran_src_yml", loader="fivetran", rank=20,
            url="https://raw.githubusercontent.com/fivetran/dbt_salesforce_source/main/models/src_salesforce.yml",
            cite="fivetran/dbt_salesforce_source@main models/src_salesforce.yml",
        ),
    ),
}


# ---------------------------------------------------------------------------------------
# Fetch — the only network path, and it is explicit
# ---------------------------------------------------------------------------------------


def fetch(url: str, timeout: int = 30) -> Optional[str]:
    request = urllib.request.Request(url, headers={"Accept": "text/plain"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None


# ---------------------------------------------------------------------------------------
# Parsers — one per reference shape
# ---------------------------------------------------------------------------------------


def parse_fivetran_src_yml(text: str) -> Dict[str, List[Dict[str, str]]]:
    """`src_<name>.yml` -> {table: [{name, description}]}.

    Parsed with a scanner rather than a YAML loader on purpose: these files carry Jinja in
    load-bearing positions (`schema: "{{ var('hubspot_schema', 'hubspot') }}"`) and a
    loader either rejects it or re-emits it quoted. The shape being read is two fixed
    indentation levels deep, which a scanner handles exactly.
    """
    tables: Dict[str, List[Dict[str, str]]] = {}
    table: Optional[str] = None
    column: Optional[Dict[str, str]] = None

    for line in text.splitlines():
        table_match = re.match(r"^      - name:\s*(\S+)\s*$", line)
        if table_match:
            table = table_match.group(1)
            tables.setdefault(table, [])
            column = None
            continue
        if table is None:
            continue
        column_match = re.match(r"^          - name:\s*(\S+)\s*$", line)
        if column_match:
            column = {"name": column_match.group(1), "description": ""}
            tables[table].append(column)
            continue
        if column is not None:
            description = re.match(r"^            description:\s*(.+?)\s*$", line)
            if description:
                column["description"] = description.group(1).strip().strip("'\"")
        # A new top-level key ends the tables block.
        if re.match(r"^  - name:\s*\S+", line) or re.match(r"^\S", line):
            table, column = None, None
    return {k: v for k, v in tables.items() if v}


def parse_dlt_settings(text: str) -> Dict[str, List[Dict[str, str]]]:
    """`DEFAULT_<OBJECT>_PROPS` tuples -> {object: [{name}]}.

    These are the properties the dlt source requests by default, so they are a floor on
    what the loaded table carries rather than its full width — recorded as such, because
    a floor presented as a contract is the same overstatement as an invented list.
    """
    out: Dict[str, List[Dict[str, str]]] = {}
    for match in re.finditer(
        r"DEFAULT_(\w+?)_PROPS\s*(?::[^=]*)?=\s*[\(\[](.*?)[\)\]]", text, re.S
    ):
        entity = match.group(1).lower()
        names = re.findall(r"[\"']([A-Za-z_][\w]*)[\"']", match.group(2))
        if names:
            out[entity] = [{"name": n, "description": ""} for n in dict.fromkeys(names)]
    return out


PARSERS = {
    "fivetran_src_yml": parse_fivetran_src_yml,
    "dlt_settings_py": parse_dlt_settings,
}


def refresh(connector: str) -> Dict[str, Any]:
    """Fetch every reference for a connector into the committed cache."""
    refs = REFERENCES.get(connector)
    if not refs:
        return {"status": "skip",
                "reason": f"no references declared for {connector!r}; "
                          f"known: {', '.join(sorted(REFERENCES))}"}

    payload: Dict[str, Any] = {
        "generated_by": "scripts/source_schema_derive.py --refresh",
        "connector": connector,
        "note": (
            "Published raw-layer schemas, fetched from the repositories cited below. This "
            "file is committed so derivation is offline and deterministic; refresh it "
            "deliberately, never as part of a sync stage."
        ),
        "sources": [],
    }
    problems: List[str] = []
    for ref in refs:
        text = fetch(ref.url)
        if text is None:
            problems.append(f"{ref.cite}: unreachable")
            continue
        tables = PARSERS[ref.kind](text)
        if not tables:
            problems.append(f"{ref.cite}: parsed no tables")
            continue
        payload["sources"].append({
            "kind": ref.kind, "cite": ref.cite, "url": ref.url,
            "loader": ref.loader, "rank": ref.rank,
            "tables": {k: v for k, v in sorted(tables.items())},
            "table_count": len(tables),
            "column_count": sum(len(v) for v in tables.values()),
        })

    if not payload["sources"]:
        return {"status": "fail", "reason": "; ".join(problems) or "nothing fetched"}

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{connector}.json"
    content = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    changed = (path.read_text(encoding="utf-8") if path.exists() else None) != content
    if changed:
        path.write_text(content, encoding="utf-8")
    return {
        "status": "changed" if changed else "ok",
        "cache": str(path.relative_to(REPO)),
        "sources": [{"cite": s["cite"], "tables": s["table_count"],
                     "columns": s["column_count"]} for s in payload["sources"]],
        "problems": problems,
    }


# ---------------------------------------------------------------------------------------
# Matching our table names to the reference's
# ---------------------------------------------------------------------------------------


def _normalise(name: str) -> str:
    """`companies` -> `company`, `deal_stages` -> `deal_stage`. Convention, not meaning."""
    name = name.lower().strip()
    for suffix, replacement in (("ies", "y"), ("ses", "s"), ("s", "")):
        if name.endswith(suffix) and len(name) > len(suffix) + 1:
            return name[: -len(suffix)] + replacement
    return name


def match_table(our_table: str, reference_tables: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """(reference table, how it matched) or None. The `how` is what a reviewer reads."""
    if our_table in reference_tables:
        return our_table, "exact"
    ours = _normalise(our_table)
    for candidate in reference_tables:
        if _normalise(candidate) == ours:
            return candidate, f"singular/plural of {candidate!r}"
    # Exact and singular/plural only. A prefix rule was tried and produced wrong columns
    # on the first real run: `deal_pipelines` normalises to `deal_pipeline`, which starts
    # with `deal`, so it matched dlt's `deal` object and inherited `amount`, `closedate`
    # and `dealname` — deal properties attributed to the pipeline table. A pipeline is not
    # a deal, and a contract assembled from that reads as verified. An honest miss is
    # reported and costs a lookup; a wrong match is invisible and generates tests that
    # enforce it (rule 5).
    return None


# ---------------------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------------------


def declared_tables(use_case: Path, source_name: str) -> Tuple[List[str], Dict[str, bool], Optional[Path]]:
    """(table names, already-has-columns, the sources.yml holding them)."""
    project = use_case / "dbt_project"
    for path in sorted(project.rglob("sources.yml")):
        text = path.read_text(encoding="utf-8")
        block = re.search(
            rf"^  - name:\s*{re.escape(source_name)}\s*$(.*?)(?=^  - name:\s|\Z)",
            text, re.M | re.S,
        )
        if not block:
            continue
        body = block.group(1)
        tables: List[str] = []
        has_columns: Dict[str, bool] = {}
        for entry in re.finditer(r"^      - name:\s*(\S+)\s*$(.*?)(?=^      - name:\s|\Z)",
                                 body, re.M | re.S):
            name = entry.group(1)
            tables.append(name)
            has_columns[name] = bool(re.search(r"^\s+columns:\s*$", entry.group(2), re.M))
        return tables, has_columns, path
    return [], {}, None


def derive(use_case: Path, source_name: str, connector: str) -> Dict[str, Any]:
    cache_path = CACHE_DIR / f"{connector}.json"
    if not cache_path.exists():
        return {"status": "skip",
                "reason": f"no {cache_path.relative_to(REPO)} — run "
                          f"--connector {connector} --refresh first"}
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    tables, has_columns, sources_path = declared_tables(use_case, source_name)
    if not tables:
        return {"status": "skip",
                "reason": f"no source named {source_name!r} declares any tables"}

    derived: Dict[str, Any] = {}
    unmatched: List[str] = []
    dropped: Dict[str, List[str]] = {}

    for table in tables:
        columns: Dict[str, Dict[str, str]] = {}
        matches: List[str] = []
        cross_reference: List[str] = []
        ordered = sorted(cache["sources"], key=lambda s: s.get("rank", 100))
        preferred_loader = ordered[0].get("loader") if ordered else None
        for source in ordered:
            found = match_table(table, source["tables"])
            if not found:
                continue
            ref_table, how = found
            if source.get("loader") != preferred_loader:
                # A different ingestion tool's naming for the same table. Recorded so the
                # wider inventory stays visible, never merged into the contract: a table
                # cannot carry both `email` and `property_email`.
                names = [c["name"] for c in source["tables"][ref_table]
                         if not VENDOR_LOAD_COLUMNS.match(c["name"])]
                cross_reference.append(
                    f"{source['cite']} -> {ref_table} ({how}): {len(names)} column(s) "
                    f"under the {source.get('loader')} convention, e.g. "
                    f"{', '.join(names[:5])}"
                )
                continue
            matches.append(f"{source['cite']} -> {ref_table} ({how})")
            for column in source["tables"][ref_table]:
                name = column["name"]
                if name in columns:
                    continue
                if VENDOR_LOAD_COLUMNS.match(name):
                    dropped.setdefault(table, []).append(
                        f"{name}: the reference connector's own load bookkeeping"
                    )
                    continue
                description = column.get("description", "")
                if DOC_REFERENCE.search(description):
                    description = ""
                columns[name] = {
                    "name": name,
                    "description": description,
                    "cited_from": f"{source['cite']} :: {ref_table}.{name}",
                }
        if not columns:
            unmatched.append(table)
            continue
        derived[table] = {
            "already_declared": has_columns.get(table, False),
            "matched_via": matches,
            "columns": list(columns.values()),
            "dropped": dropped.get(table, []),
            "cross_reference": cross_reference,
        }

    return {
        "status": "ok",
        "source": source_name,
        "connector": connector,
        "sources_yml": str(sources_path.relative_to(REPO)) if sources_path else None,
        "tables_declared": len(tables),
        "tables_derived": len(derived),
        "columns_derived": sum(len(t["columns"]) for t in derived.values()),
        "unmatched": unmatched,
        "dropped_columns": sum(len(v) for v in dropped.values()),
        "derived": derived,
        "citations": [s["cite"] for s in cache["sources"]],
    }


def render_proposal(slug: str, result: Dict[str, Any]) -> str:
    lines = [
        f"# Raw source columns derived for `{result['source']}`. NOT AN ARTIFACT — a proposal.",
        "#",
        "# Written by `source_schema_derive.py`. Every column below was read out of a",
        "# published connector schema and carries the exact file and identifier it came",
        "# from. Nothing here is recalled and nothing is guessed: a column the references",
        "# do not mention is absent rather than approximated.",
        "#",
        "# `confirmed: false` on every table. These describe what the connector vendor",
        "# publishes, not what this tenant's warehouse actually landed — the two differ",
        "# whenever the ingestion is configured with a subset, a different API version, or",
        "# a column-renaming transform. Confirmation is a human act against OpenMetadata",
        "# once the data lands; `openmetadata_feedback.py --propose` carries corrections",
        "# back.",
        "#",
        "# Sources consulted:",
    ]
    for citation in result["citations"]:
        lines.append(f"#   - {citation}")
    lines += [
        "#",
        f"#     python3 scripts/source_schema_derive.py --use-case {slug} "
        f"--source {result['source']} --promote",
        "",
        "version: 1",
        "source: derived",
        f"raw_source: {result['source']}",
        "",
        "tables:",
    ]
    for table in sorted(result["derived"]):
        entry = result["derived"][table]
        lines.append(f"  {table}:")
        lines.append("    confirmed: false")
        if entry["already_declared"]:
            lines.append("    # this table already declares `columns:` — --promote will skip it")
        for match in entry["matched_via"]:
            lines.append(f"    # matched: {match}")
        for reason in entry.get("dropped", []):
            lines.append(f"    # dropped: {reason}")
        for other in entry.get("cross_reference", []):
            lines.append(f"    # cross-reference (NOT this project's names): {other}")
        lines.append("    columns:")
        for column in entry["columns"]:
            lines.append(f"      - name: {column['name']}")
            if column["description"]:
                safe = column["description"].replace('"', "'")[:200]
                lines.append(f"        description: \"{safe}\"")
            lines.append(f"        # from: {column['cited_from']}")
        lines.append("")
    if result["unmatched"]:
        lines.append("# Declared here but absent from every reference consulted. Not guessed —")
        lines.append("# these need the catalog, or a reference this tool does not yet know:")
        for table in result["unmatched"]:
            lines.append(f"#   {table}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------
# Promotion into sources.yml
# ---------------------------------------------------------------------------------------


def promote(use_case: Path, source_name: str, check: bool) -> Dict[str, Any]:
    """Insert `columns:` blocks as text. Never round-trips the YAML.

    Same rule as `dbt_column_memory.py --emit-source-columns`: these files carry Jinja in
    load-bearing positions and a YAML library either rejects it or re-emits it quoted so
    dbt stops rendering it, and a round-trip drops every comment. The gate is that the
    diff is insertions only.
    """
    proposal_path = use_case / "ontology" / "proposals" / PROPOSAL_NAME
    if not proposal_path.exists():
        return {"status": "skip", "reason": f"no {proposal_path.relative_to(REPO)}"}
    proposal = _miniyaml.load(proposal_path.read_text(encoding="utf-8")) or {}
    tables = proposal.get("tables") or {}
    if not tables:
        return {"status": "skip", "reason": "the proposal declares no tables"}

    _, has_columns, sources_path = declared_tables(use_case, source_name)
    if sources_path is None:
        return {"status": "skip", "reason": f"no sources.yml declares {source_name!r}"}

    text = sources_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    insertions: List[Tuple[int, str]] = []
    promoted: List[str] = []
    skipped: List[str] = []

    for table in sorted(tables):
        entry = tables[table] or {}
        if has_columns.get(table):
            skipped.append(f"{table}: already declares columns:")
            continue
        columns = entry.get("columns") or []
        if not columns:
            skipped.append(f"{table}: no derived columns")
            continue
        # Find this table's block and the line after its last property.
        anchor = None
        for index, line in enumerate(lines):
            if re.match(rf"^      - name:\s*{re.escape(table)}\s*$", line):
                anchor = index
                break
        if anchor is None:
            skipped.append(f"{table}: not found in {sources_path.name}")
            continue
        end = anchor + 1
        while end < len(lines) and (lines[end].startswith("        ")
                                    or not lines[end].strip()):
            if not lines[end].strip() and end + 1 < len(lines) and \
                    not lines[end + 1].startswith("        "):
                break
            end += 1

        block = [f"        {GENERATED_BANNER}\n",
                 "        # Derived from a published connector schema; unconfirmed against\n",
                 "        # this tenant's warehouse. See ontology/proposals/" + PROPOSAL_NAME + "\n",
                 "        columns:\n"]
        for column in columns:
            block.append(f"          - name: {column['name']}\n")
            if column.get("description"):
                safe = str(column["description"]).replace('"', "'")[:200]
                block.append(f"            description: \"{safe}\"\n")
        insertions.append((end, "".join(block)))
        promoted.append(table)

    if not insertions:
        return {"status": "ok", "promoted": 0, "skipped": skipped,
                "sources_yml": str(sources_path.relative_to(REPO))}

    for position, block in sorted(insertions, reverse=True):
        lines.insert(position, block)
    if not check:
        sources_path.write_text("".join(lines), encoding="utf-8")

    return {
        "status": "changed",
        "promoted": len(promoted),
        "tables": promoted,
        "skipped": skipped,
        "sources_yml": str(sources_path.relative_to(REPO)),
    }


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--use-case")
    parser.add_argument("--source", help="the `sources:` name, e.g. hubspot_api")
    parser.add_argument("--connector", help="the reference key, e.g. hubspot "
                                            "(defaults to --source minus _api)")
    parser.add_argument("--refresh", action="store_true",
                        help="NETWORK: refetch the published schemas into references/")
    parser.add_argument("--write", action="store_true", help="write the proposal")
    parser.add_argument("--promote", action="store_true",
                        help="insert the derived columns into sources.yml")
    parser.add_argument("--check", action="store_true", help="write nothing")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    if args.refresh:
        connector = args.connector or (args.source or "").replace("_api", "")
        result = refresh(connector)
        print(json.dumps(result, ensure_ascii=False) if args.format == "json"
              else f"{result['status']}: " + (result.get("reason") or result.get("cache", "")))
        if args.format == "text" and result.get("sources"):
            for source in result["sources"]:
                print(f"  {source['cite']}: {source['tables']} table(s), "
                      f"{source['columns']} column(s)")
        return 0 if result["status"] in ("ok", "changed") else 1

    if not (args.use_case and args.source):
        parser.error("--use-case and --source are required unless --refresh")
    use_case = _paths.require_use_case_dir(args.use_case, REPO)
    connector = args.connector or args.source.replace("_api", "")

    if args.promote:
        result = promote(use_case, args.source, args.check)
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"{result['status']}: {result.get('reason') or ''}")
            for table in result.get("tables", []):
                print(f"  + {table}")
            for reason in result.get("skipped", []):
                print(f"  skip {reason}")
        return 0

    result = derive(use_case, args.source, connector)
    if result["status"] == "skip":
        print(json.dumps(result, ensure_ascii=False) if args.format == "json"
              else f"skip: {result['reason']}")
        return 0

    proposal_path = use_case / "ontology" / "proposals" / PROPOSAL_NAME
    content = render_proposal(args.use_case, result)
    changed = (proposal_path.read_text(encoding="utf-8")
               if proposal_path.exists() else None) != content
    if args.write and changed and not args.check:
        proposal_path.parent.mkdir(parents=True, exist_ok=True)
        proposal_path.write_text(content, encoding="utf-8")

    if args.format == "json":
        print(json.dumps({**result, "derived": list(result["derived"])},
                         ensure_ascii=False))
    else:
        print(f"{result['tables_derived']} of {result['tables_declared']} declared table(s) "
              f"derived, {result['columns_derived']} column(s)")
        for citation in result["citations"]:
            print(f"  cited: {citation}")
        for table in sorted(result["derived"]):
            entry = result["derived"][table]
            flag = " (already declared)" if entry["already_declared"] else ""
            print(f"  {table}: {len(entry['columns'])} column(s){flag}")
            for match in entry["matched_via"]:
                print(f"      via {match}")
            for other in entry.get("cross_reference", []):
                print(f"      x-ref {other[:120]}")
        for table in result["unmatched"]:
            print(f"  [unmatched] {table} — absent from every reference consulted")
        if args.write:
            print(f"\n{'would write' if args.check else 'wrote'} "
                  f"{proposal_path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
