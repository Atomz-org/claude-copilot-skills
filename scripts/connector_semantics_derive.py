#!/usr/bin/env python3
"""Derive one connector's annotations and topology from its published schema.

Scoped to a single connector on purpose. A project-wide bootstrap writes a hundred
decisions nobody asked for into files a reviewer then has to audit in bulk; adding a
connector is the moment its semantics are actually being thought about, and it is the
only moment the person running this knows which answers are plausible.

`source_schema_derive.py` answers *which columns exist*. This answers the two questions
that come next:

    annotations   what each column is — role, additivity, unit, PII, and a definition
    topology      which entities the connector carries and how they reference each other

Both come out as proposals under `ontology/proposals/`, never as artifacts, and both are
re-runnable: a second pass after the real schema lands rewrites the proposal and leaves
every promoted decision alone. That is the room for later changes — the derivation is
disposable, the promotion is not.

Where the answers come from
---------------------------

**Facets are derived by `column_annotations.derive`, not reimplemented here.** That
function already encodes six rules that were each wrong first — an identifier suffix
outranks a numeric cast, a definition outranks a name shape, a BAS account number is not
a bank account, a price per unit is non-additive, `Discount` contains `count`, and a
regex cannot read a cast. Deriving facets a second way here would reintroduce all six.
What this module adds is the *definition* to feed it: the connector vendor's own column
description, which is exactly the evidence `derive()` weights highest and the one thing a
new connector has no local source for.

**Relationships come from column names that match another table in the same connector.**
`deal.deal_pipeline_id` names `deal_pipeline`, which the same schema declares — so the
reference is evidence, not a guess. A `*_id` matching nothing is reported, never invented
into a relationship with a table that does not exist.

**Nothing is asserted about a concept.** Which ontology concept a connector supplies is
declared in `ontology/connectors.yml` and generated from there; this module reads that
declaration and reports coverage against it. It does not add concepts, because "this
connector probably supplies Customers" is the catalogue expectation that
`plans_to_supply` exists to keep out of `supplies`.

Usage:
    python3 scripts/connector_semantics_derive.py --use-case <slug> --connector hubspot
    python3 scripts/connector_semantics_derive.py --use-case <slug> --connector hubspot --write
    python3 scripts/connector_semantics_derive.py --use-case <slug> --connector hubspot --promote
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

import _miniyaml  # noqa: E402
import _paths  # noqa: E402

import column_annotations as ca  # noqa: E402
import lm_propose as lp  # noqa: E402
import source_schema_derive as ssd  # noqa: E402

REPO = _paths.REPO

TOPOLOGY_NAME = "topology.{connector}.yml"

# A column whose name ends this way names another entity. Checked against the tables the
# same reference declares — a suffix alone is a naming habit, a suffix that resolves to a
# declared table is a reference.
FK_SUFFIX = re.compile(r"^(?P<stem>.+?)_?(id|_id)$", re.I)


def use_case_dir(slug: str) -> Path:
    return _paths.require_use_case_dir(slug, REPO)


# ---------------------------------------------------------------------------------------
# Reading the connector's published schema
# ---------------------------------------------------------------------------------------


def preferred_tables(connector: str) -> Tuple[Dict[str, List[Dict[str, str]]], str, List[str]]:
    """(tables, citation, problems) from the highest-ranked reference for this connector.

    One reference, never a union: two ingestion tools name the same field differently, and
    a merged answer describes no warehouse. `source_schema_derive` records the ranking and
    why; this reads it rather than re-deciding.
    """
    return _reference(connector, key=lambda s: s.get("rank", 100))


def richest_tables(connector: str) -> Tuple[Dict[str, List[Dict[str, str]]], str, List[str]]:
    """The reference declaring the most tables, whichever tool lands them.

    Topology and contracts want different references, and conflating them costs real
    coverage. A *contract* must come from the preferred loader, because `property_email`
    and `email` are the same field under two tools and only one of them will exist in the
    warehouse. A connector's *entity graph* has no such problem: `deal` referencing
    `deal_pipeline` is a fact about HubSpot, not about who loaded it. Measured here — dlt
    publishes default properties for 6 CRM objects and Fivetran declares 61 tables with
    real foreign keys, so deriving topology from the preferred reference found 0
    relationships and 6 dangling ids.
    """
    return _reference(connector, key=lambda s: -int(s.get("table_count") or 0))


def _reference(connector: str, key) -> Tuple[Dict[str, List[Dict[str, str]]], str, List[str]]:
    path = ssd.CACHE_DIR / f"{connector}.json"
    if not path.exists():
        return {}, "", [f"no {path.relative_to(REPO)} — run source_schema_derive --refresh"]
    cache = json.loads(path.read_text(encoding="utf-8"))
    sources = sorted(cache.get("sources") or [], key=key)
    if not sources:
        return {}, "", ["the reference cache holds no sources"]
    chosen = sources[0]
    tables = {
        name: [c for c in columns if not ssd.VENDOR_LOAD_COLUMNS.match(c["name"])]
        for name, columns in (chosen.get("tables") or {}).items()
    }
    return {k: v for k, v in tables.items() if v}, chosen["cite"], []


def declared_concepts(use_case: Path, connector: str) -> List[str]:
    """What this connector supplies, read from the artifacts. Never added to.

    `index.json` first: an `implemented` connector's concepts are derived from the
    manifest, so `expected_concepts` in `connectors.yml` is empty for it by design and
    reading only that reports `none` for a connector with adapters. `connectors.yml` is
    the fallback, which is where a `planned` connector's expectations live.
    """
    index_path = use_case / "ontology" / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for entry in index.get("connectors") or []:
            if str(entry.get("key")) == connector:
                concepts = list(entry.get("concepts") or [])
                if concepts:
                    return concepts
    path = use_case / "ontology" / "connectors.yml"
    if not path.exists():
        return []
    data = _miniyaml.load(path.read_text(encoding="utf-8")) or {}
    for row in data.get("connectors") or []:
        if str(row.get("key")) == connector:
            return list(row.get("expected_concepts") or [])
    return []


# ---------------------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------------------


@dataclass
class Annotation:
    column: str
    table: str
    facets: Dict[str, Any]
    definition: str
    evidence: List[str]
    confidence: str
    # Where the definition came from: the column's own reference entry, the same table in
    # the description reference, or a bare name that resolved against no table at all.
    definition_scope: str = "own"


VENDOR_PREFIX = re.compile(r"^(property|properties)_", re.I)


def one_line(text: str) -> str:
    """A vendor description collapsed to a single line.

    The reference now carries real block scalars, so a `|` description arrives with its
    line breaks intact — which is right for the cache and wrong for here. This module
    renders a description twice into line-oriented text: as `definition: "..."` and as a
    `# evidence:` comment. A newline in either splits the line, and the second half of a
    split comment is no longer a comment — it becomes a stray YAML key in the middle of a
    proposal.
    """
    return " ".join((text or "").split())


def _described(columns: List[Dict[str, str]]) -> Dict[str, str]:
    """Bare column name -> the description the vendor wrote, for one table."""
    out: Dict[str, str] = {}
    for column in columns:
        description = one_line(column.get("description") or "")
        if not description or ssd.DOC_REFERENCE.search(description):
            continue
        out.setdefault(VENDOR_PREFIX.sub("", column["name"]).lower(), description)
    return out


def scoped_description_index(
    tables: Dict[str, List[Dict[str, str]]],
) -> Dict[str, Dict[str, str]]:
    """Reference table -> {bare column name -> description}. The index that is *correct*.

    A column name is only unique inside its table. `name`, `createdate` and `description`
    each appear on a dozen HubSpot objects with a dozen different meanings, so a flat
    name -> description map answers "what does `name` mean?" with whichever table happened
    to be walked first. Measured on the committed reference: **39 of 164 bare names carry
    more than one distinct description**, and the flat index handed `company.name` the
    text "Name of Event." and all three `createdate` columns "The date the company was
    added to your account."

    This is the same defect `ssd.match_table` refuses by rejecting prefix matches — a
    pipeline is not a deal, and a product is not an event. Getting it wrong is invisible,
    because a borrowed description reads as verified.
    """
    return {table: described for table, columns in tables.items()
            if (described := _described(columns))}


def description_index(tables: Dict[str, List[Dict[str, str]]]) -> Dict[str, str]:
    """Column name (vendor prefix stripped) -> a description, ignoring which table wrote it.

    The preferred reference gives the right *names* and the richest one gives the
    *descriptions*, and for this vendor pair the two differ by one mechanical prefix:
    Fivetran lands `property_email`, dlt lands `email`. Stripping it lets a description
    reach the column it describes without adopting the other tool's naming — and a
    description is the evidence `column_annotations.derive` weights above every name shape
    and cast, so without this bridge almost every facet comes back unset.

    Used **only** where `scoped_description_index` has no answer, and marked as a fallback
    in the evidence when it is: a bare name that resolved against no table may well be
    describing another entity. Measured on the committed reference, all four fallbacks
    are — `product` and `quote` appear in Fivetran's schema not at all, so their columns
    borrow from whatever else declares a `name` or a `createdate`.
    """
    out: Dict[str, str] = {}
    for columns in tables.values():
        for bare, description in _described(columns).items():
            out.setdefault(bare, description)
    return out


def derive_annotations(tables: Dict[str, List[Dict[str, str]]], citation: str,
                       descriptions: Optional[Dict[str, str]] = None,
                       description_citation: str = "",
                       scoped: Optional[Dict[str, Dict[str, str]]] = None,
                       ) -> Tuple[List[Annotation], List[str]]:
    """One candidate per (table, column), facets from `column_annotations.derive`.

    A borrowed description is looked up **in the matching table first**. `ssd.match_table`
    resolves our table name against the description reference's — exact or singular/plural,
    never a prefix — and only when that finds nothing does the bare-name index answer, with
    the evidence line saying so. A description is the highest-weighted evidence the facet
    deriver reads, so the difference between the two lookups is the difference between
    "the name of the company" and "Name of Event."

    Abstentions are kept out rather than emitted blank: a column the deriver could not
    read is honestly unannotated, and `--coverage` already exists to list those.
    """
    out: List[Annotation] = []
    abstained: List[str] = []
    for table in sorted(tables):
        match = ssd.match_table(table, scoped) if scoped else None
        in_table = scoped.get(match[0], {}) if (scoped and match) else {}
        for column in tables[table]:
            name = column["name"]
            description = one_line(column.get("description") or "")
            scope = "own"
            borrowed = ""
            if not description:
                bare = VENDOR_PREFIX.sub("", name).lower()
                borrowed = in_table.get(bare, "")
                scope = "scoped"
                if not borrowed and descriptions:
                    borrowed = descriptions.get(bare, "")
                    scope = "fallback"
                description = borrowed
            candidate = ca.derive(name, set(), None, description)
            facets = {
                facet: candidate.get(facet)
                for facet in ("role", "additivity", "unit", "pii")
                if candidate.get(facet)
            }
            # `pii: none` is `derive()`'s default when no shape matched, not a decision
            # anyone made. Emitting it asserts somebody checked, which is the same defect
            # as tagging an unannotated column `Additive` — absence has to keep meaning
            # "nobody decided".
            if facets.get("pii") == "none":
                facets.pop("pii")
            if not facets and not description:
                abstained.append(f"{table}.{name}: no description and no readable name shape")
                continue
            evidence = [f"{citation} :: {table}.{name}"]
            if borrowed and scope == "scoped":
                evidence.append(
                    f"description via {description_citation} :: {match[0]}.{name} "
                    f"({match[1]}, vendor prefix stripped): {borrowed[:100]}")
            elif borrowed:
                # Named, because it is the one definition here that may belong to another
                # entity: nothing resolved `table` in the description reference, so this
                # text is whichever table happened to declare the same bare column name.
                evidence.append(
                    f"description via {description_citation}, BARE-NAME FALLBACK — no "
                    f"`{table}` in that reference, so this may describe another entity: "
                    f"{borrowed[:90]}")
            elif description:
                evidence.append(f"vendor description: {description[:120]}")
            for facet, value in facets.items():
                why = candidate.get(f"{facet}_evidence") or candidate.get("evidence")
                if isinstance(why, list) and why:
                    evidence.append(f"{facet}={value}: {why[0]}")
            out.append(Annotation(
                column=name, table=table, facets=facets, definition=description,
                evidence=evidence,
                confidence=str(candidate.get("confidence") or "low"),
                definition_scope=scope if borrowed else "own",
            ))
    return out, abstained


def render_annotations(slug: str, connector: str, citation: str,
                       annotations: List[Annotation], abstained: List[str]) -> str:
    lines = [
        f"# `{connector}` column annotations, derived. NOT AN ARTIFACT — a proposal.",
        "#",
        f"# Written by `connector_semantics_derive.py --connector {connector}`. Facets come",
        "# from `column_annotations.derive` — the same function the rest of the project",
        "# uses, so the six derivation rules it encodes apply here too. What this adds is",
        "# the vendor's own column description as the evidence that function weights",
        "# highest, which is the one input a connector with no landed data cannot get",
        "# locally.",
        "#",
        f"# Source: {citation}",
        "#",
        "# Every entry is `reviewed: false`. These describe what a connector vendor",
        "# publishes, not what this tenant's warehouse landed. Re-running after the real",
        "# schema arrives rewrites this file and leaves anything already promoted into",
        "# ontology/annotations.yml untouched — the derivation is disposable, the",
        "# promotion is not.",
        "#",
        f"#     python3 scripts/connector_semantics_derive.py --use-case {slug} "
        f"--connector {connector} --promote",
        "",
        "version: 1",
        f"source: {connector}-reference",
        "",
        "columns:",
    ]
    seen: set = set()
    for annotation in sorted(annotations, key=lambda a: (a.column, a.table)):
        if annotation.column in seen:
            # One decision per column name, not per (table, column): annotations are keyed
            # on the conformed column everywhere else here, and emitting the same name
            # twice would let one column be a measure in one table and a dimension in
            # another — the drift conformance exists to prevent.
            continue
        seen.add(annotation.column)
        lines.append(f"  {annotation.column}:")
        lines.append("    reviewed: false")
        lines.append(f"    confidence: {annotation.confidence}")
        for evidence in annotation.evidence:
            lines.append(f"    # evidence: {evidence}")
        for facet in ("role", "additivity", "unit", "pii"):
            if annotation.facets.get(facet):
                lines.append(f"    {facet}: {annotation.facets[facet]}")
        if annotation.definition:
            lines.append(f"    definition: {lp._q(annotation.definition)}")
        lines.append("")
    if abstained:
        lines.append("# Abstained — no description and no readable name shape. Honestly")
        lines.append("# unannotated rather than guessed:")
        for reason in abstained[:40]:
            lines.append(f"#   {reason}")
        if len(abstained) > 40:
            lines.append(f"#   ... {len(abstained) - 40} more")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------------------


def derive_topology(tables: Dict[str, List[Dict[str, str]]],
                    citation: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Entities and the references between them, both read off the same schema."""
    names = set(tables)
    normalised = {ssd._normalise(t): t for t in names}
    relationships: List[Dict[str, Any]] = []
    dangling: List[str] = []

    for table in sorted(tables):
        for column in tables[table]:
            match = FK_SUFFIX.match(column["name"])
            if not match:
                continue
            stem = match.group("stem").strip("_").lower()
            if not stem or stem == table.lower():
                continue
            target = normalised.get(ssd._normalise(stem)) or (stem if stem in names else None)
            if target is None:
                dangling.append(f"{table}.{column['name']} names `{stem}`, "
                                "which this schema does not declare")
                continue
            relationships.append({
                "from_table": table, "from_column": column["name"], "to_table": target,
                "cited_from": f"{citation} :: {table}.{column['name']}",
            })
    return relationships, dangling


def render_topology(slug: str, connector: str, citation: str,
                    tables: Dict[str, List[Dict[str, str]]],
                    relationships: List[Dict[str, Any]],
                    dangling: List[str], concepts: List[str]) -> str:
    lines = [
        f"# `{connector}` topology, derived. NOT AN ARTIFACT — a proposal.",
        "#",
        "# Entities are the tables the connector's published schema declares.",
        "# Relationships are columns whose name resolves to another table in that same",
        "# schema — evidence, not a naming habit: a `*_id` matching no declared table is",
        "# listed at the bottom and never invented into a reference.",
        "#",
        f"# Source: {citation}",
        "#",
        "# No concept is asserted here. Which ontology concepts a connector supplies is",
        "# declared in ontology/connectors.yml and generated from it; adding one here",
        "# would turn a catalogue expectation into a claim, which is exactly what",
        "# `plans_to_supply` exists to keep out of `supplies`.",
        "",
        "version: 1",
        f"source: {connector}-reference",
        "confirmed: false",
        "",
        f"declared_concepts: [{', '.join(concepts) if concepts else ''}]",
        "",
        "entities:",
    ]
    for table in sorted(tables):
        lines.append(f"  {table}:")
        lines.append(f"    columns: {len(tables[table])}")
    lines.append("")
    lines.append("relationships:")
    for relationship in sorted(relationships, key=lambda r: (r["from_table"], r["from_column"])):
        lines.append(f"  - from: {relationship['from_table']}.{relationship['from_column']}")
        lines.append(f"    to: {relationship['to_table']}")
        lines.append(f"    # from: {relationship['cited_from']}")
    if not relationships:
        lines.append("  # none — no column name resolved to another declared table")
    if dangling:
        lines.append("")
        lines.append("# Named an entity this schema does not declare. Reported, never")
        lines.append("# invented into a relationship:")
        for reason in dangling[:30]:
            lines.append(f"#   {reason}")
        if len(dangling) > 30:
            lines.append(f"#   ... {len(dangling) - 30} more")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------------------


def run(slug: str, connector: str, write: bool, check: bool) -> Dict[str, Any]:
    use_case = use_case_dir(slug)
    tables, citation, problems = preferred_tables(connector)
    if problems:
        return {"status": "skip", "reason": problems[0]}

    topo_tables, topo_citation, _ = richest_tables(connector)
    annotations, abstained = derive_annotations(
        tables, citation, description_index(topo_tables), topo_citation,
        scoped=scoped_description_index(topo_tables))
    relationships, dangling = derive_topology(topo_tables, topo_citation)
    concepts = declared_concepts(use_case, connector)

    proposals = use_case / "ontology" / "proposals"
    files = {
        lp.proposal_path(use_case, "annotations", source=connector):
            render_annotations(slug, connector, citation, annotations, abstained),
        proposals / TOPOLOGY_NAME.format(connector=connector):
            render_topology(slug, connector, topo_citation, topo_tables, relationships,
                            dangling, concepts),
    }

    changed: List[str] = []
    for path, content in sorted(files.items()):
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing == content:
            continue
        changed.append(str(path.relative_to(REPO)))
        if write and not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    return {
        "status": "ok",
        "connector": connector,
        "citation": citation,
        "entities": len(topo_tables),
        "annotation_source": citation,
        "topology_source": topo_citation,
        "annotated": len({a.column for a in annotations}),
        "abstained": len(abstained),
        "scoped_definitions": sum(1 for a in annotations if a.definition_scope == "scoped"),
        "fallback_definitions": sum(1 for a in annotations if a.definition_scope == "fallback"),
        "relationships": len(relationships),
        "dangling": len(dangling),
        "declared_concepts": concepts,
        "changed": changed,
        "written": bool(write and not check),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--use-case", required=True)
    parser.add_argument("--connector", required=True)
    parser.add_argument("--write", action="store_true", help="write the proposals")
    parser.add_argument("--promote", action="store_true",
                        help="merge reviewed annotations into ontology/annotations.yml")
    parser.add_argument("--min-confidence", choices=lp.CONFIDENCE, default="medium")
    parser.add_argument("--check", action="store_true", help="write nothing")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    use_case = use_case_dir(args.use_case)

    if args.promote:
        result = lp.promote(use_case, args.use_case, "annotations", args.min_confidence,
                            args.check, source=args.connector)
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False))
        elif result["status"] == "skip":
            print(f"skip: {result['reason']}")
        else:
            print(f"promoted {result['promoted']} entry(ies) into {result['artifact']}")
            for name in result.get("names", [])[:20]:
                print(f"  + {name}")
            for reason in result["held"][:10]:
                print(f"  held  {reason}")
        return 0

    payload = run(args.use_case, args.connector, args.write, args.check)
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    if payload["status"] == "skip":
        print(f"skip: {payload['reason']}")
        return 0

    print(f"{payload['connector']}: {payload['entities']} entity(ies), "
          f"{payload['annotated']} column annotation(s), "
          f"{payload['relationships']} relationship(s)")
    print(f"  cited: {payload['citation']}")
    print(f"  {payload['abstained']} column(s) abstained (no description, no name shape)")
    if payload["scoped_definitions"] or payload["fallback_definitions"]:
        print(f"  {payload['scoped_definitions']} definition(s) borrowed from the matching "
              f"table, {payload['fallback_definitions']} by bare name only")
    if payload["fallback_definitions"]:
        print("    a bare-name definition may describe another entity — the evidence "
              "line says so")
    if payload["dangling"]:
        print(f"  {payload['dangling']} `*_id` column(s) name no declared table — reported")
    print(f"  declared concepts: {', '.join(payload['declared_concepts']) or 'none'}")
    for rel in payload["changed"]:
        print(f"  {'wrote' if payload['written'] else 'would write'} {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
