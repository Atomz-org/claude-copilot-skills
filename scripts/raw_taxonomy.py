#!/usr/bin/env python3
"""Build the taxonomy and conceptual model from the raw layer, before any dbt model exists.

Every other ontology artifact in this repository is derived from `manifest.json`, which
means it describes what the dbt project **is**. That is the right direction for keeping an
ontology honest and the wrong direction for building one: it cannot exist until the models
do, so the conceptual model that rule 6 requires — "the conceptual model precedes the
physical one" — has nowhere to live except somebody's head.

This script is the other direction. Its inputs are the raw layer and the use-case spec; its
output is a declaration of what the project *should* build, which the models are then written
against. The two directions meet at `--plan`: every entity declared here is either realised
by a dbt model or reported as an open gap, so the conceptual model is falsifiable the same
way `test_every_declared_dbt_model_exists` makes the generated ontology falsifiable.

    raw layer  ->  taxonomy.yml  ->  conceptual-model.json  ->  dbt models  ->  ontology/*.ttl
    (declared)     (hand-authored)   (derived, this script)    (written)       (derived, generated)

**One input is genuinely unknown and it is the only hand-authored one.** Whether a table
called `tblCust01` is a Customer, whether `Email` or `CustomerNumber` identifies it, and what
one row of the resulting mart means are semantic judgements. Nothing in a schema decides them.
So `--propose` reads the raw layer and emits *candidates with their evidence*, a human or an
agent confirms them into `ontology/taxonomy.yml`, and everything downstream is derived from
that file. Same split, and for the same reason, as `connectors.yml`: the catalogue is written
down once, the artifacts are regenerated forever.

Three rules decide whether the output can be trusted, and each is enforced rather than
documented:

- **An attribute that is not a declared source column does not exist.** Rule 5, mechanically.
  `sources.yml` states what this project depends on, so an entity attribute that traces to no
  declared column is reported as a problem and kept out of the model. The failure this
  prevents is an ontology that reads beautifully and describes a warehouse nobody can build.
- **A grain is declared or the entity is incomplete.** Rule 4 wants one sentence — "one row
  per customer per tenant" — before any SQL. It cannot be derived from a schema, so the
  taxonomy must carry it, and an entity without one is reported. Silence here is what makes a
  measure double-count three layers downstream while every test passes.
- **A concept nothing supplies is a gap, not an omission.** A use-case that needs `Contract`
  with no raw table behind it is the most valuable thing this script can tell you, and it is
  exactly the finding that disappears if unmapped concepts are quietly skipped.

Usage:
    python3 scripts/raw_taxonomy.py --use-case <slug> --propose      # candidates + evidence
    python3 scripts/raw_taxonomy.py --use-case <slug>                # write the artifact
    python3 scripts/raw_taxonomy.py --use-case <slug> --check        # the CI gate
    python3 scripts/raw_taxonomy.py --use-case <slug> --plan         # what is not built yet
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _manifest import Manifest, die  # noqa: E402
import _miniyaml  # noqa: E402
import _paths  # noqa: E402
from _paths import REPO  # noqa: E402

import ontology_generator as og  # noqa: E402

ARTIFACT = "conceptual-model.json"
TAXONOMY = "taxonomy.yml"

# A column name shaped like an identifier. Used only to *propose* — a proposal is evidence
# for a human, never a decision.
#
# The stem is optional on the first pattern and required on the second, which is not a
# stylistic difference. A bare `Number` or `Code` is what a table calls its own key
# (`accounts.Number` is the account number), so requiring a stem there hid the real natural
# key of every such table behind whatever foreign key happened to be declared beside it —
# `dim_accounts` proposed `OrgId` and `SalaryCode` while `Number` was not a candidate at
# all. A bare `Id` stays out: it identifies a row in whichever table it sits in and says
# nothing about which entity that is, so it is noise in every proposal it would appear in.
KEY_SHAPES = (
    re.compile(r"^(?P<stem>[A-Za-z]*?)(Number|No|Code|Key)$"),
    re.compile(r"^(?P<stem>[A-Za-z]+)Id$"),
    re.compile(r"^(?P<stem>)(Email|Ssn|OrgNo|VatNumber|Guid|Uuid)$", re.IGNORECASE),
)

# Table-name noise that never carries meaning: the connector's own bookkeeping. Excluded
# from proposals because mapping an audit log to a business concept is how a taxonomy gets
# large and useless.
NOISE_TABLES = re.compile(
    r"(^|_)(_dlt|dlt_|audit|log|logs|history|meta|metadata|sync|state|version|"
    r"loads|schema|migrations?|tmp|temp|staging_only)(_|$)",
    re.IGNORECASE,
)


def use_case_dir(slug: str) -> Path:
    """`_paths.require_use_case_dir` bound to this module's REPO; absence exits 2."""
    return _paths.require_use_case_dir(slug, REPO)


# ---------------------------------------------------------------------------------------
# The raw layer
# ---------------------------------------------------------------------------------------


@dataclass
class RawTable:
    source: str
    table: str
    columns: List[str] = field(default_factory=list)
    declared_in: str = ""

    @property
    def key(self) -> str:
        """`(source, table)`, never table alone.

        Two `sources.yml` here declare three and five sources; nothing stops two of them
        exposing a `customers`. Keying by table alone does not collide today and is one
        added table away from silently merging two sources' schemas into one entity.
        """
        return f"{self.source}.{self.table}"


def read_raw_layer(project: Path) -> Tuple[List[RawTable], List[str]]:
    """Every source table this project declares, with the columns it depends on.

    Read with `_miniyaml` rather than a full YAML library for the reason the source-column
    emitter inserts text rather than round-tripping: these files carry Jinja in load-bearing
    positions (`schema: fortnox_api_{{ var('demo_uid', var('uid')) }}`), and a strict parser
    either rejects it or re-emits it quoted so dbt stops rendering it.
    """
    tables: List[RawTable] = []
    problems: List[str] = []
    if not project.exists():
        return tables, problems
    for path in sorted(project.rglob("sources.yml")):
        rel = path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else str(path)
        try:
            data = _miniyaml.load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # pragma: no cover - malformed yaml is a project defect
            problems.append(f"{rel}: could not parse ({type(exc).__name__})")
            continue
        for source in data.get("sources", []) or []:
            name = str(source.get("name") or "")
            if not name:
                continue
            for table in source.get("tables", []) or []:
                tname = str(table.get("name") or "")
                if not tname:
                    continue
                cols = [
                    str(c.get("name"))
                    for c in (table.get("columns") or [])
                    if isinstance(c, dict) and c.get("name")
                ]
                tables.append(RawTable(name, tname, sorted(cols), rel))
    return tables, problems


# ---------------------------------------------------------------------------------------
# Proposing — evidence, never decisions
# ---------------------------------------------------------------------------------------


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("sses") or word.endswith("ses"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def concept_candidates(table: str, vocabulary: Dict[str, str]) -> List[Tuple[str, str]]:
    """Concepts whose name matches this raw table, each with the evidence that matched it.

    Name matching only. A schema cannot tell you that `tblCust01` is a Customer, and this
    function does not pretend otherwise — it returns nothing for a table it cannot match,
    which is the honest answer and leaves the mapping to the person who knows.
    """
    stem = re.sub(r"^(raw|src|stg|tbl)[_-]?", "", table.lower())
    stem = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    forms = {stem, _singular(stem)}
    forms |= {f"{stem}s", f"{_singular(stem)}s"}

    out: List[Tuple[str, str]] = []
    for concept in vocabulary:
        body = re.sub(r"^(dim|fact)_", "", concept)
        if body in forms or _singular(body) in forms:
            evidence = "exact name match" if body == stem else "name match after normalising"
            out.append((concept, evidence))
    return out


# Below this many column-declaring tables, prevalence says nothing — see `propose`.
MIN_TABLES_FOR_PARTITION = 10


def propose(
    tables: List[RawTable], vocabulary: Dict[str, str], existing: Dict[str, Any]
) -> Dict[str, Any]:
    """Candidate table->concept mappings and natural keys, each carrying why it is proposed.

    A table already decided in `taxonomy.yml` is reported as `confirmed` and never
    re-proposed. Overwriting a human's mapping with a name match would make this script the
    authority on a fact it only guessed at — the same rule that stops the source-column
    emitter touching a table that already declares `columns:`.
    """
    decided: Dict[str, str] = {}
    for concept, entry in (existing.get("entities") or {}).items():
        for row in entry.get("sources") or []:
            decided[f"{row.get('source')}.{row.get('table')}"] = concept

    proposed: Dict[str, List[Dict[str, Any]]] = {}
    unmatched: List[Dict[str, str]] = []
    noise: List[str] = []

    for raw in tables:
        if raw.key in decided:
            continue
        if NOISE_TABLES.search(raw.table):
            noise.append(raw.key)
            continue
        cands = concept_candidates(raw.table, vocabulary)
        if not cands:
            unmatched.append({
                "source": raw.source,
                "table": raw.table,
                "columns": len(raw.columns),
                "note": "no concept in the vocabulary matches this name — map it by hand or "
                        "add the concept to ontology.yml",
            })
            continue
        for concept, evidence in cands:
            proposed.setdefault(concept, []).append({
                "source": raw.source,
                "table": raw.table,
                "evidence": evidence,
                "declared_columns": len(raw.columns),
            })

    # A natural key candidate is a key-shaped column declared by more than one of the tables
    # proposed for a concept. One table cannot evidence a *cross-source* key, so a
    # single-table concept gets candidates by shape alone and says so.
    by_key = {t.key: t for t in tables}

    # A key-shaped column on most tables in the project is the partition, not the entity.
    # `OrgId` is on 81 of 112 declaring tables here and the next-most-common is on 20, so
    # the separation is not a judgement call. It stays a candidate — it is genuinely part of
    # the grain, "one row per customer per tenant" — but it ranks last, because on its own it
    # identifies the tenant and names no entity. Same reasoning that excludes a bare `Id`.
    declaring = [t for t in tables if t.columns]
    prevalence: Dict[str, int] = {}
    for raw in declaring:
        for col in set(raw.columns):
            prevalence[col] = prevalence.get(col, 0) + 1
    # A floor before "on most tables" means anything: on two tables a column is on 100% of
    # them and that is not evidence of anything. Ten is where the real corpus separates
    # cleanly (81 of 112 versus a next-most-common 20) and a fixture-sized one cannot.
    partition_at = len(declaring) / 2 if len(declaring) >= MIN_TABLES_FOR_PARTITION else 0
    partition_cols = {c for c, n in prevalence.items() if partition_at and n > partition_at}

    keys: Dict[str, List[Dict[str, Any]]] = {}
    for concept, rows in proposed.items():
        counts: Dict[str, int] = {}
        for row in rows:
            for col in by_key[f"{row['source']}.{row['table']}"].columns:
                if any(shape.match(col) for shape in KEY_SHAPES):
                    counts[col] = counts.get(col, 0) + 1
        candidates = [
            {
                "column": col,
                "declared_by": n,
                "of_tables": len(rows),
                "evidence": (
                    f"on {prevalence.get(col, 0)} of {len(declaring)} tables project-wide — "
                    f"a partition key, not an entity key"
                    if col in partition_cols else
                    f"key-shaped, declared by {n} of {len(rows)} proposed tables"
                    if n > 1 else "key-shaped in the only proposed table — unconfirmed"
                ),
            }
            for col, n in sorted(
                counts.items(),
                key=lambda kv: (kv[0] in partition_cols, -kv[1], kv[0]),
            )
        ]
        if candidates:
            # The cap applies to entity candidates. A demoted partition key survives it,
            # because the grain sentence needs it — "one row per customer **per tenant**" —
            # and a reviewer who never sees the column cannot write that.
            entity = [c for c in candidates if c["column"] not in partition_cols]
            partition = [c for c in candidates if c["column"] in partition_cols]
            keys[concept] = entity[:5] + partition[:1]

    return {
        "proposed": {k: proposed[k] for k in sorted(proposed)},
        "natural_key_candidates": keys,
        "unmatched_tables": sorted(unmatched, key=lambda r: (r["source"], r["table"])),
        "excluded_as_noise": sorted(noise),
        "already_confirmed": len(decided),
    }


def render_taxonomy_stub(proposal: Dict[str, Any], slug: str) -> str:
    """A `taxonomy.yml` a human finishes, not one they accept.

    Every proposal lands commented out with its evidence beside it, and `grain` is present
    and empty on purpose: rule 4 wants one sentence before any SQL, no schema can supply it,
    and a template that pre-fills it would be inventing the one thing this file exists to
    capture.
    """
    lines = [
        "# Raw layer -> business concepts. HAND-AUTHORED; nothing regenerates this file.",
        "#",
        f"# Scaffolded by `raw_taxonomy.py --use-case {slug} --propose`. Every mapping below is",
        "# a *name match* with its evidence — a schema cannot know that a table is a Customer.",
        "# Confirm each one, delete what is wrong, and write the grain. Then run:",
        "#",
        f"#     python3 scripts/raw_taxonomy.py --use-case {slug}",
        "",
        "version: 1",
        "",
        "entities:",
    ]
    for concept, rows in proposal["proposed"].items():
        core = og.CONCEPT_CLASS.get(concept, "")
        lines.append(f"  {concept}:")
        if core:
            lines.append(f"    core_class: {core}")
        lines.append("    # Rule 4: one row per WHAT? Required — an entity without it is")
        lines.append("    # reported incomplete, because a measure at the wrong grain")
        lines.append("    # double-counts while every test passes.")
        lines.append('    grain: ""')
        keys = proposal["natural_key_candidates"].get(concept) or []
        if keys:
            lines.append("    # Candidates, most-evidenced first. Uncomment the real one.")
            for cand in keys:
                lines.append(f"    #   {cand['column']}  — {cand['evidence']}")
        lines.append("    natural_key: []")
        lines.append("    sources:")
        for row in rows:
            lines.append(f"      - source: {row['source']}")
            lines.append(f"        table: {row['table']}")
            lines.append(f"        # {row['evidence']}, "
                         f"{row['declared_columns']} declared column(s)")
        lines.append("")
    if proposal["unmatched_tables"]:
        lines.append("# Raw tables no concept name matched. Each is either a concept this")
        lines.append("# vocabulary lacks (add it to ontology.yml) or genuinely out of scope:")
        for row in proposal["unmatched_tables"]:
            lines.append(f"#   {row['source']}.{row['table']}  "
                         f"({row['columns']} declared column(s))")
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------
# Building the conceptual model
# ---------------------------------------------------------------------------------------


def read_taxonomy(ontology: Path) -> Dict[str, Any]:
    path = ontology / TAXONOMY
    if not path.exists():
        return {}
    return _miniyaml.load(path.read_text(encoding="utf-8")) or {}


def local_concept_classes(ontology: Path) -> Dict[str, str]:
    """Only the concepts *this use-case* declares, before the shared vocabulary is merged.

    `og.read_config` returns the merge, which is right for classifying a concept and wrong
    for deciding what counts as a gap: the shared map describes what an invoice is in every
    domain, so a concept in it that this project has no data for was never requested here.
    """
    path = ontology / "ontology.yml"
    if not path.exists():
        return {}
    data = _miniyaml.load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in (data.get("concept_classes") or {}).items()}


def build_model(
    taxonomy: Dict[str, Any],
    tables: List[RawTable],
    cfg: og.OntologyConfig,
    slug: str,
    ontology_dir: Path,
) -> Tuple[Dict[str, Any], List[str]]:
    """The conceptual model, with every attribute traced to a declared source column."""
    by_key = {t.key: t for t in tables}
    problems: List[str] = []
    entities: List[Dict[str, Any]] = []
    mapped_tables: Set[str] = set()

    for concept in sorted(taxonomy.get("entities") or {}):
        entry = (taxonomy["entities"] or {})[concept] or {}
        core = entry.get("core_class") or cfg.concept_class.get(concept)
        if not core:
            problems.append(
                f"{concept}: no core class — classify it in ontology.yml's concept_classes "
                f"rather than letting this script guess"
            )

        rows = entry.get("sources") or []
        resolved: List[Dict[str, str]] = []
        for row in rows:
            key = f"{row.get('source')}.{row.get('table')}"
            if key not in by_key:
                problems.append(
                    f"{concept}: taxonomy maps {key}, which no sources.yml declares"
                )
                continue
            mapped_tables.add(key)
            resolved.append({
                "source": str(row.get("source")),
                "table": str(row.get("table")),
                "role": str(row.get("role") or ("primary" if not resolved else "secondary")),
            })
        if not resolved:
            problems.append(f"{concept}: no resolvable source table")

        # Rule 5, mechanically: an attribute is a column some mapped table declares. The
        # union rather than the intersection, with the declaring tables named, so a column
        # only one source carries is visible as exactly that rather than silently conformed.
        attributes: List[Dict[str, Any]] = []
        seen: Dict[str, List[str]] = {}
        for row in resolved:
            raw = by_key[f"{row['source']}.{row['table']}"]
            for col in raw.columns:
                seen.setdefault(col, []).append(raw.key)
        for col in sorted(seen):
            attributes.append({
                "name": col,
                "declared_by": sorted(seen[col]),
                "shared_by": len(seen[col]),
                "universal": len(seen[col]) == len(resolved) and len(resolved) > 1,
            })

        natural_key = [str(k) for k in (entry.get("natural_key") or [])]
        for key_col in natural_key:
            if key_col not in seen:
                problems.append(
                    f"{concept}: natural key '{key_col}' is declared by no mapped source "
                    f"table — declare it in sources.yml or correct the taxonomy"
                )

        grain = str(entry.get("grain") or "").strip()
        if not grain:
            problems.append(
                f"{concept}: no grain. Rule 4 wants one sentence — 'one row per X per Y' — "
                f"before any SQL is written for it"
            )

        kind = "fact" if concept.startswith("fact_") else "dimension"
        entities.append({
            "concept": concept,
            "entity": og._local(concept),
            "id": f"{cfg.topo}{og._local(concept)}",
            "core_class": core,
            "kind": kind,
            "grain": grain or None,
            "natural_key": natural_key,
            # Rule 12: chosen, never defaulted. Absent means undecided, which is a state
            # worth seeing rather than a silent type 1.
            "scd": str(entry.get("scd") or "") or None,
            "sources": resolved,
            "attribute_count": len(attributes),
            "attributes": attributes,
        })

    # A relationship is proposed only where a key-shaped column names another entity that
    # this taxonomy actually declares. Two facts already written down, joined — not a guess
    # about what the warehouse ought to look like.
    stems = {e["entity"].lower(): e for e in entities}
    relationships: List[Dict[str, Any]] = []
    for ent in entities:
        for attr in ent["attributes"]:
            match = None
            for shape in KEY_SHAPES[:2]:
                match = shape.match(attr["name"])
                if match:
                    break
            if not match:
                continue
            stem = _singular(match.group("stem").lower())
            target = stems.get(stem)
            if not target or target["entity"] == ent["entity"]:
                continue
            relationships.append({
                "from": ent["entity"],
                "to": target["entity"],
                "via": attr["name"],
                "declared_by": attr["declared_by"],
                "evidence": "key-shaped column naming a declared entity",
                "confidence": "proposed",
            })

    # A gap is a concept somebody wrote down for *this* domain and no raw table supplies.
    # The shared ERP/CRM vocabulary is not that: it describes what an invoice is across
    # every use-case, so reporting all 58 of its concepts as gaps buries the two that
    # matter under fifty-six that nobody asked for — rule 3, and the same
    # cap-lists-then-serialize rule that stopped the untested-model dump. The shared ones
    # are reported as a count with a sample, which is context rather than a work item.
    declared = {e["concept"] for e in entities}
    local_concepts = set(local_concept_classes(ontology_dir))
    gaps = [
        {
            "concept": concept,
            "core_class": cfg.concept_class.get(concept),
            "reason": "declared in this use-case's ontology.yml, no raw table mapped to it",
        }
        for concept in sorted(local_concepts - declared)
    ]
    unused = sorted(set(cfg.concept_class) - declared - local_concepts)
    unmapped = sorted({t.key for t in tables} - mapped_tables)

    model = {
        "use_case": slug,
        "title": cfg.title,
        "generated_by": "scripts/raw_taxonomy.py",
        "normative_source": (
            "ontology/taxonomy.yml for the mappings; the columns declared in sources.yml "
            "for every attribute"
        ),
        "prefixes": {"erp": cfg.erp, "crm": cfg.crm, "conn": cfg.conn, "topo": cfg.topo},
        "provenance": {
            # Counts of committed inputs only. Nothing run-dependent — a timestamp or a
            # cache counter here makes the artifact change when the project has not, and
            # `--check` is then permanently red.
            "raw_tables_declared": len(tables),
            "raw_tables_mapped": len(mapped_tables),
            "declared_columns": sum(len(t.columns) for t in tables),
            "entities": len(entities),
        },
        "entities": entities,
        "relationships": sorted(
            relationships, key=lambda r: (r["from"], r["to"], r["via"])
        ),
        "gaps": gaps,
        "shared_vocabulary_unused": {
            "count": len(unused),
            "sample": unused[:10],
            "note": "concepts the shared ERP/CRM vocabulary knows that this raw layer does "
                    "not supply. Context, not a work list — a concept nobody asked for is "
                    "not a gap.",
        },
        "unmapped_raw_tables": unmapped,
    }
    return model, problems


# ---------------------------------------------------------------------------------------
# Closing the loop against dbt
# ---------------------------------------------------------------------------------------


def plan(model: Dict[str, Any], manifest_path: Optional[Path]) -> Dict[str, Any]:
    """What this conceptual model declares that the dbt project has not built yet.

    The reason the model is worth writing before the SQL: the difference between what is
    declared and what exists is a work list, and it is computed rather than remembered.
    """
    if not manifest_path or not manifest_path.exists():
        return {"available": False, "reason": "no manifest — run artifacts/refresh.sh"}
    man = Manifest.load(str(manifest_path))
    names = {n.get("name") for n in man.nodes.values() if n.get("resource_type") == "model"}
    built: List[Dict[str, str]] = []
    todo: List[Dict[str, Any]] = []
    for ent in model["entities"]:
        concept = ent["concept"]
        hits = sorted(n for n in names if n and n.endswith(concept))
        (built if hits else todo).append(
            {"concept": concept, "entity": ent["entity"], "models": hits}
            if hits else
            {
                "concept": concept,
                "entity": ent["entity"],
                "kind": ent["kind"],
                "grain": ent["grain"],
                "sources": [f"{s['source']}.{s['table']}" for s in ent["sources"]],
                "attribute_count": ent["attribute_count"],
            }
        )
    return {
        "available": True,
        "declared": len(model["entities"]),
        "built": len(built),
        "not_built": len(todo),
        "todo": todo,
    }


# ---------------------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Taxonomy and conceptual model from the raw layer, before dbt models.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--use-case", required=True)
    p.add_argument("--propose", action="store_true",
                   help="scaffold ontology/taxonomy.yml from the raw layer; refuses to "
                        "overwrite an existing one")
    p.add_argument("--plan", action="store_true",
                   help="report which declared entities the dbt project has not built")
    p.add_argument("--check", action="store_true",
                   help="exit 1 if the artifact is stale or the taxonomy has problems")
    p.add_argument("--manifest", help="manifest.json (default: <project>/target/manifest.json)")
    p.add_argument("--format", choices=("text", "json"), default="text")
    args = p.parse_args(argv)

    use_case = use_case_dir(args.use_case)
    project = use_case / "dbt_project"
    ontology = use_case / "ontology"
    cfg = og.read_config(ontology, args.use_case)

    tables, problems = read_raw_layer(project)
    if not tables:
        # A use-case with no declared sources is a correct early state, not a failure. A
        # gate that goes red on it gets switched off within a week, taking the real
        # failures with it.
        payload = {"use_case": args.use_case, "status": "skip",
                   "reason": "no sources.yml declares any table yet"}
        print(json.dumps(payload, ensure_ascii=False) if args.format == "json"
              else f"skip: {payload['reason']}")
        return 0

    taxonomy = read_taxonomy(ontology)

    if args.propose:
        target = ontology / TAXONOMY
        proposal = propose(tables, cfg.concept_class, taxonomy)
        if target.exists():
            print(
                f"REFUSED: {target.relative_to(REPO)} already exists. Proposals are a "
                f"scaffold for a decision, and rewriting one already made would make this "
                f"script the authority on a fact it guessed at.\n"
                f"  Delete it to re-scaffold, or edit it by hand.",
                file=sys.stderr,
            )
            if args.format == "json":
                print(json.dumps({"use_case": args.use_case, "refused": True,
                                  **proposal}, ensure_ascii=False))
            return 1
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_taxonomy_stub(proposal, args.use_case), encoding="utf-8")
        if args.format == "json":
            print(json.dumps({"use_case": args.use_case,
                              "written": str(target.relative_to(REPO)),
                              **proposal}, ensure_ascii=False))
        else:
            print(f"scaffolded {target.relative_to(REPO)}")
            print(f"  {len(proposal['proposed'])} concept(s) proposed from "
                  f"{len(tables)} declared raw table(s)")
            print(f"  {len(proposal['unmatched_tables'])} table(s) matched no concept")
            print(f"  {len(proposal['excluded_as_noise'])} excluded as pipeline bookkeeping")
            print("\nEvery mapping is a name match. Confirm each one and write the grain.")
        return 0

    if not taxonomy:
        payload = {"use_case": args.use_case, "status": "skip",
                   "reason": f"no ontology/{TAXONOMY} — run --propose first"}
        print(json.dumps(payload, ensure_ascii=False) if args.format == "json"
              else f"skip: {payload['reason']}")
        return 0

    model, model_problems = build_model(taxonomy, tables, cfg, args.use_case, ontology)
    problems += model_problems

    manifest_path = (
        Path(args.manifest) if args.manifest else project / "target/manifest.json"
    )
    if args.plan:
        result = plan(model, manifest_path)
        if args.format == "json":
            print(json.dumps({"use_case": args.use_case, **result}, ensure_ascii=False))
            return 0
        if not result["available"]:
            print(f"skip: {result['reason']}")
            return 0
        print(f"declared: {result['declared']}   built: {result['built']}   "
              f"not built: {result['not_built']}")
        for row in result["todo"]:
            print(f"\n  {row['entity']}  ({row['kind']}, {row['attribute_count']} attributes)")
            print(f"    grain:   {row['grain'] or '[NEEDS INPUT]'}")
            print(f"    sources: {', '.join(row['sources'])}")
        return 0

    target = ontology / ARTIFACT
    content = json.dumps(model, indent=2, ensure_ascii=False) + "\n"
    existing = target.read_text(encoding="utf-8") if target.exists() else None
    changed = existing != content
    if changed and not args.check:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    if args.format == "json":
        print(json.dumps({
            "use_case": args.use_case,
            "artifact": str(target.relative_to(REPO)),
            "changed": changed,
            "entities": len(model["entities"]),
            "relationships": len(model["relationships"]),
            "gaps": len(model["gaps"]),
            "raw_tables_mapped": model["provenance"]["raw_tables_mapped"],
            "raw_tables_declared": model["provenance"]["raw_tables_declared"],
            "problems": problems,
        }, ensure_ascii=False))
        return 1 if problems or (args.check and changed) else 0

    print(f"use-case:   {args.use_case}")
    print(f"raw layer:  {model['provenance']['raw_tables_mapped']} of "
          f"{model['provenance']['raw_tables_declared']} declared table(s) mapped, "
          f"{model['provenance']['declared_columns']} declared column(s)")
    print(f"entities:   {len(model['entities'])} "
          f"({sum(1 for e in model['entities'] if e['kind'] == 'fact')} fact, "
          f"{sum(1 for e in model['entities'] if e['kind'] == 'dimension')} dimension)")
    print(f"relations:  {len(model['relationships'])} proposed")
    print(f"gaps:       {len(model['gaps'])} declared concept(s) with no raw table"
          f"  ({model['shared_vocabulary_unused']['count']} shared-vocabulary "
          f"concept(s) unused here)")
    if problems:
        print(f"\nproblems ({len(problems)}):")
        for problem in problems:
            print(f"  {problem}")
    if args.check:
        if changed:
            print(f"\n{target.relative_to(REPO)} is stale — run without --check")
            return 1
        if not problems:
            print("\nConceptual model is current.")
    elif changed:
        print(f"\nwrote {target.relative_to(REPO)}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
