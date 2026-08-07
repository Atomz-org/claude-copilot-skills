#!/usr/bin/env python3
"""Fill the fields no schema contains, with a language model, without inventing facts.

Every generator in this repository stops at the same wall. `raw_taxonomy.py` derives which
raw tables *look like* a Customer and refuses to write the grain; `column_annotations.py`
derives a role from a cast and abstains on additivity, PII, and what a column means. Those
refusals are correct — rule 5 — and they leave real work undone: measured on
enhanza-analytics, **183 of 272 conformed columns carry no annotation** and no `taxonomy.yml`
exists at all, so the stage that should declare what the project ought to build skips.

A language model can do that work, and it can also do it catastrophically: a fabricated enum
passes every `accepted_values` test *because it generated them*, and a fabricated grain makes
a measure double-count while every test stays green. So the module is built around what
makes a generated field trustworthy rather than around the generation:

1. **The script assembles the evidence; the model only decides.** Every item ships with what
   this repository already knows — cast types, the raw source columns it traces to, sibling
   columns of the same concept, the project's own descriptions of neighbours. A model asked
   "what is `AmountPerUnit`?" recalls; a model asked "here are its casts, its lineage, and
   its concept's other columns — classify it" reads. Only the second is checkable.
2. **Output lands in a proposal, never in the artifact.** `ontology/proposals/*.lm.yml`,
   every entry stamped `source: lm`, with its confidence, the evidence it used, and
   `reviewed: false`. `--promote` moves only what a human has marked reviewed. A proposal
   never overwrites a decision — the same rule that stops `--propose` touching an existing
   `annotations.yml`.
3. **Four refusals at `--apply`, each a way a model lies here.** A column or table that does
   not exist; a closed domain with no citable source; a definition that restates the name;
   and a claim whose stated evidence is not in the item it was given. Each is dropped with a
   reason, not clipped into the file with a low confidence.
4. **No hidden API call.** The default backend is the agent that runs this: `--prepare`
   writes a batch of grounded questions, `--apply` reads the answers back. `--backend
   anthropic` exists for unattended runs and needs both `ANTHROPIC_API_KEY` and the
   `anthropic` package; without either it skips with the remedy named, the way every
   optional dependency here does.

Usage:
    python3 scripts/lm_propose.py --use-case <slug> --target annotations --prepare
    python3 scripts/lm_propose.py --use-case <slug> --target annotations --apply answers.json
    python3 scripts/lm_propose.py --use-case <slug> --target annotations --review
    python3 scripts/lm_propose.py --use-case <slug> --target annotations --promote
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _manifest import die  # noqa: E402
import _miniyaml  # noqa: E402
import _paths  # noqa: E402
from _paths import REPO  # noqa: E402

import column_annotations as ca  # noqa: E402
import raw_taxonomy as rt  # noqa: E402

TARGETS = ("annotations", "taxonomy")
CONFIDENCE = ("high", "medium", "low")

# A definition that only rearranges the column's own words says nothing. `OrgName` ->
# "the name of the org" is the shape; it passes a non-empty check and teaches nobody.
_STOPWORDS = {"the", "a", "an", "of", "for", "in", "on", "this", "that", "is", "its", "and"}


def use_case_dir(slug: str) -> Path:
    """`_paths.require_use_case_dir` bound to this module's REPO; absence exits 2."""
    return _paths.require_use_case_dir(slug, REPO)


def proposal_path(use_case: Path, target: str, source: str = "lm") -> Path:
    """`annotations.lm.yml` is a model's proposal; `annotations.hubspot.yml` a derived one.

    The suffix is a parameter rather than a constant because more than one thing now
    drafts an annotation — a language model here, and `connector_semantics_derive.py`
    from a connector vendor's published schema. Both promote through `promote()` below,
    so the promoted artifact reads as one file with one convention and the
    `# promoted from proposals/...` comment is what records which drafted a line.
    """
    return use_case / "ontology" / "proposals" / f"{target}.{source}.yml"


# ---------------------------------------------------------------------------------------
# Evidence assembly
# ---------------------------------------------------------------------------------------


def _lineage_by_column(use_case: Path) -> Dict[str, List[Dict[str, str]]]:
    """Which raw source column each conformed column traces back to, per connector.

    This is the single most useful piece of evidence for "what does this column mean", and
    it is the one a model cannot possibly recall: `ContributionValue` means whatever the
    SQL that produced it did, and column-memory already resolved that chain.
    """
    path = use_case / "ontology" / "column-memory.json"
    if not path.exists():
        return {}
    memory = json.loads(path.read_text(encoding="utf-8"))
    out: Dict[str, List[Dict[str, str]]] = {}
    for binding in memory.get("bindings") or []:
        out.setdefault(str(binding.get("column")), []).append({
            "connector": str(binding.get("connector")),
            "source_model": str(binding.get("source_model")),
            "source_column": str(binding.get("source_column")),
            "transform": str(binding.get("transform")),
        })
    return out


def _siblings_by_concept(use_case: Path) -> Dict[str, List[str]]:
    """The other conformed columns of each concept — the context a column sits in.

    `Net` is unreadable alone and obvious beside `SalesValue`, `PurchasePrice`, and
    `ContributionValue` on the same invoice row.
    """
    path = use_case / "ontology" / "column-memory.json"
    if not path.exists():
        return {}
    memory = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(c.get("concept")): list(c.get("conformed") or [])
        for c in (memory.get("contracts") or [])
    }


def annotation_items(use_case: Path, limit: Optional[int]) -> List[Dict[str, Any]]:
    """One question per unannotated conformed column, ranked by how many connectors carry it.

    Ranked because a reviewer who stops halfway should have spent the budget where the
    answer covers the most (column, connector) pairs — the same ordering `--coverage` uses.
    """
    columns = ca.conformed_columns(use_case)
    project = use_case / "dbt_project"
    types = ca.cast_types(project)
    domains = ca.declared_domains(project)
    definitions = ca.declared_definitions(project)
    lineage = _lineage_by_column(use_case)
    siblings = _siblings_by_concept(use_case)

    source_path = use_case / "ontology" / ca.SOURCE
    decided = set()
    if source_path.exists():
        decided = set(
            (_miniyaml.load(source_path.read_text(encoding="utf-8")) or {}).get("columns") or {})

    items: List[Dict[str, Any]] = []
    for name in sorted(columns, key=lambda c: (-len(columns[c]["connectors"]), c)):
        if name in decided:
            continue
        meta = columns[name]
        derived = ca.derive(name, types.get(name, set()), domains.get(name),
                            definitions.get(name, ""))
        concept_siblings: List[str] = []
        for concept in meta["concepts"]:
            concept_siblings += [c for c in siblings.get(concept, []) if c != name][:12]
        items.append({
            "id": name,
            "column": name,
            "concepts": meta["concepts"],
            "connectors": meta["connectors"],
            "carried_by_count": len(meta["connectors"]),
            "cast_types": sorted(types.get(name, set())),
            "harvested_definition": definitions.get(name, ""),
            "derived": {k: derived[k] for k in ("role", "additivity", "unit", "pii")},
            "derived_evidence": derived["evidence"],
            "abstained_by_deriver": derived["abstained"],
            # Capped: a model reads the first few and the rest is context it pays for and
            # never uses. The same cap is why `--coverage` shows 20 and not 183.
            "lineage": lineage.get(name, [])[:6],
            "concept_siblings": sorted(set(concept_siblings))[:16],
        })
        if limit and len(items) >= limit:
            break
    return items


def taxonomy_items(use_case: Path, limit: Optional[int]) -> List[Dict[str, Any]]:
    """One question per candidate concept: is this the entity, what identifies it, what is
    one row?

    The grain is the field this exists for. No schema contains it, `raw_taxonomy.py` leaves
    it empty on purpose, and an entity without one is reported incomplete — so a use-case
    with no `taxonomy.yml` has no declaration of what it ought to build at all.
    """
    project = use_case / "dbt_project"
    tables, problems = rt.read_raw_layer(project)
    if problems and not tables:
        return []
    vocabulary = dict(rt.og.CONCEPT_CLASS)
    vocabulary.update(rt.local_concept_classes(use_case / "ontology"))

    source_path = use_case / "ontology" / "taxonomy.yml"
    existing = {}
    if source_path.exists():
        existing = _miniyaml.load(source_path.read_text(encoding="utf-8")) or {}
    proposal = rt.propose(tables, vocabulary, existing)

    by_key = {t.key: t for t in tables}
    items: List[Dict[str, Any]] = []
    for concept, rows in proposal["proposed"].items():
        columns: List[str] = []
        for row in rows:
            raw = by_key.get(f"{row['source']}.{row['table']}")
            if raw:
                columns += list(raw.columns)
        items.append({
            "id": concept,
            "concept": concept,
            "core_class": vocabulary.get(concept, ""),
            "candidate_tables": [
                {"source": r["source"], "table": r["table"],
                 "declared_columns": r["declared_columns"], "matched_because": r["evidence"]}
                for r in rows
            ],
            "natural_key_candidates": proposal["natural_key_candidates"].get(concept, []),
            "declared_columns": sorted(set(columns))[:40],
        })
        if limit and len(items) >= limit:
            break
    return items


# ---------------------------------------------------------------------------------------
# The batch a model answers
# ---------------------------------------------------------------------------------------

ANNOTATION_INSTRUCTIONS = """\
For each item, decide what the conformed column MEANS. Answer only from the evidence in the
item — its casts, its lineage to raw source columns, the project's own harvested definition,
and the sibling columns of its concept. Do not use recall about the source system.

Return JSON: {"answers": [{...}]} with one object per item:

  id            the item's id, verbatim
  role          identifier | measure | dimension | timestamp | flag | text
  additivity    REQUIRED when role is measure, else omit.
                  additive      a flow: sums across every dimension including time
                  semi_additive a level: sums across everything EXCEPT time (a balance,
                                a stock quantity, a headcount)
                  non_additive  a ratio, a rate, a percentage, or a UNIT PRICE — summing
                                it across rows produces a number with no referent
  unit          currency | count | quantity | percent | duration | date | none
  pii           none | direct | quasi | indirect
                  direct identifies a person alone (email, phone, national id, bank account)
                  quasi  re-identifies only in combination (street address, birth date)
                  indirect identifies through a join
  definition    one sentence saying what the column means. Must add information the column
                NAME does not already carry. If the evidence does not support one, omit the
                whole answer for that item rather than paraphrasing the name.
  domain        OMIT unless the evidence names the permitted values AND where they came
                from. {"closed": true, "values": [...], "source": "<citable source>"}.
                An enum you recall rather than read is the single worst thing you can put
                here: it generates the test that would have caught it.
  confidence    high | medium | low
  evidence_used a list of short strings, each quoting or naming a field of THIS item that
                drove the answer. An answer whose evidence is not in the item is dropped.

Omit any item you cannot answer from its evidence. A missing answer is a visible gap; a
guessed one is invisible."""

TAXONOMY_INSTRUCTIONS = """\
For each item, decide whether the candidate raw tables really are that business concept,
which column identifies one of them, and what ONE ROW means.

Return JSON: {"answers": [{...}]} with one object per item:

  id            the item's id, verbatim
  accept        true if these tables are that concept, false to reject the mapping
  grain         REQUIRED when accept is true. One sentence: "one row per X per Y". This is
                the field nothing can derive and the reason this batch exists — a measure
                true at a coarser grain double-counts while every test passes (rule 4).
  natural_key   a list of column names that identify one row. Every name MUST appear in the
                item's declared_columns; a key that is not a declared column does not exist.
  scd_type      1 | 2 | none — whether history matters for this entity (rule 12). Omit if
                the evidence does not say.
  tables        optional: the subset of candidate_tables that belong, as "source.table"
                strings, when only some do.
  confidence    high | medium | low
  evidence_used short strings naming the fields of THIS item that drove the answer.

Omit any item whose grain you cannot state from the evidence. An invented grain is the one
error here that never surfaces as a failure."""


def build_batch(use_case: Path, slug: str, target: str, limit: Optional[int]) -> Dict[str, Any]:
    items = (annotation_items if target == "annotations" else taxonomy_items)(use_case, limit)
    return {
        "use_case": slug,
        "target": target,
        "generated_by": "scripts/lm_propose.py",
        "instructions": (ANNOTATION_INSTRUCTIONS if target == "annotations"
                         else TAXONOMY_INSTRUCTIONS),
        "item_count": len(items),
        "items": items,
    }


# ---------------------------------------------------------------------------------------
# Validation — the four ways a generated field is wrong
# ---------------------------------------------------------------------------------------


def _evidence_is_grounded(evidence: List[str], item: Dict[str, Any]) -> bool:
    """Does any cited evidence actually appear in the item the model was handed?

    The cheapest tell that a model answered from recall is evidence that reads plausibly
    and names nothing in front of it — "the Fortnox API documents this as a percentage".
    A token of length four or more has to occur somewhere in the item; a citation that
    survives that is at worst a misreading of real evidence, which review catches, rather
    than a fabrication, which it usually does not.

    Two things do not count, and both were accepted before they were excluded:

    - **The item's own name.** "the Incoterms standard defines these terms" grounded for
      `TermsOfDelivery` on the token `terms`. Restating what is being asked about is not
      evidence, and it is the shape a confident fabrication takes.
    - **The field names.** Matching the whole item as text let "I know how ERP systems
      model this" ground on the key `source_model`. Only values are facts.

    Names are matched **as written**: `fortnox_api__articles` grounds, the loose word
    `article` does not. A citation that survives is at worst a misreading of real evidence,
    which review catches, rather than a fabrication, which it usually does not.
    """
    own = ca._name_words(str(item.get("id", "")))
    facts: List[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str):
            facts.append(value)
        elif isinstance(value, list):
            for element in value:
                collect(element)
        elif isinstance(value, dict):
            for element in value.values():
                collect(element)

    # `derived_evidence` is deliberately absent: it is the deriver's own prose ("name ends
    # in an identifier suffix"), so counting it would let generic wording ground itself.
    for key in ("concepts", "connectors", "cast_types", "harvested_definition", "lineage",
                "concept_siblings", "declared_columns", "candidate_tables",
                "natural_key_candidates", "core_class", "derived"):
        collect(item.get(key))

    known = {t.lower() for text in facts
             for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", str(text))} - own
    for line in evidence:
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", str(line)):
            if token.lower() in known:
                return True
    return False


def _restates_the_name(name: str, definition: str) -> bool:
    words = {w for w in re.findall(r"[a-z]+", definition.lower()) if w not in _STOPWORDS}
    name_words = ca._name_words(name)
    return bool(words) and words <= name_words


def validate_annotation(answer: Dict[str, Any], item: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    problems: List[str] = []
    name = str(answer.get("id") or "")
    role = str(answer.get("role") or "")
    if role not in ca.ROLES:
        problems.append(f"{name}: role {role or '(empty)'!r} is not a facet value")
        return None, problems

    additivity = str(answer.get("additivity") or "") or None
    if role == "measure" and additivity not in ca.ADDITIVITY:
        problems.append(f"{name}: a measure must state additivity (rule 11)")
        return None, problems
    if additivity and role != "measure":
        problems.append(f"{name}: additivity is meaningless on a {role}")
        return None, problems

    pii = str(answer.get("pii") or "none")
    if pii not in ca.PII_CLASSES:
        problems.append(f"{name}: pii {pii!r} is not a class")
        return None, problems

    unit = str(answer.get("unit") or "") or None
    if unit and unit not in ca.UNITS:
        problems.append(f"{name}: unit {unit!r} is not a unit")
        return None, problems

    # The same conflict the deriver abstains on, applied to the model. `Manufacturer` casts
    # to string in every connector; an answer calling it an additive currency measure is
    # contradicted by evidence that was in the item it read. The deriver refuses to guess
    # which side is wrong here, and so does this.
    casts = {str(t).lower() for t in (item.get("cast_types") or [])}
    cast_roles = {ca.TYPE_ROLE[t] for t in casts if t in ca.TYPE_ROLE}
    if role == "measure" and cast_roles and cast_roles <= {"dimension", "text"}:
        problems.append(
            f"{name}: answered as a measure, but every cast in the item is "
            f"{'/'.join(sorted(casts))} — the answer contradicts its own evidence")
        return None, problems

    definition = str(answer.get("definition") or "").strip()
    if not definition:
        problems.append(f"{name}: no definition — the facets say how to aggregate it, "
                        f"never what it is")
        return None, problems
    if ca.PLACEHOLDER.search(definition):
        problems.append(f"{name}: definition is a placeholder")
        return None, problems
    if _restates_the_name(name, definition):
        problems.append(f"{name}: definition only rearranges the column name "
                        f"({definition[:50]!r}) and adds nothing")
        return None, problems

    domain = answer.get("domain") or None
    if domain:
        values = [str(v) for v in (domain.get("values") or [])]
        source = str(domain.get("source") or "").strip()
        if not values or not source:
            # Refused rather than downgraded: a closed domain generates the very
            # accepted_values test that would have caught it being wrong (rule 5).
            problems.append(f"{name}: closed domain without values or a citable source — "
                            f"dropped, the rest of the annotation kept")
            domain = None
        else:
            domain = {"closed": True, "values": values, "source": source}

    confidence = str(answer.get("confidence") or "low")
    if confidence not in CONFIDENCE:
        confidence = "low"
    evidence = [str(e) for e in (answer.get("evidence_used") or []) if str(e).strip()]
    if not evidence:
        problems.append(f"{name}: no evidence cited — an unevidenced answer is a recollection")
        return None, problems
    if not _evidence_is_grounded(evidence, item):
        problems.append(f"{name}: cited evidence names nothing in the item it was given")
        return None, problems

    return {
        "role": role, "additivity": additivity, "unit": unit, "pii": pii,
        "definition": definition, "domain": domain,
        "confidence": confidence, "evidence_used": evidence,
    }, problems


def validate_taxonomy(answer: Dict[str, Any], item: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    problems: List[str] = []
    concept = str(answer.get("id") or "")
    if not answer.get("accept", False):
        return None, [f"{concept}: rejected by the model — the name match was not the concept"]

    grain = str(answer.get("grain") or "").strip()
    if not grain:
        problems.append(f"{concept}: no grain (rule 4) — the one field this batch exists for")
        return None, problems
    if ca.PLACEHOLDER.search(grain):
        problems.append(f"{concept}: grain is a placeholder")
        return None, problems

    declared = {c.lower() for c in item.get("declared_columns") or []}
    key = [str(k) for k in (answer.get("natural_key") or [])]
    unknown = [k for k in key if k.lower() not in declared]
    if unknown:
        # The failure this catches is a plausible key nobody declared — it survives review
        # because it reads correctly, and breaks at the first `unique` test on a column
        # that does not exist.
        problems.append(f"{concept}: natural key names {', '.join(unknown)}, which no "
                        f"candidate table declares")
        return None, problems
    if not key:
        problems.append(f"{concept}: no natural key from the declared columns")
        return None, problems

    scd = str(answer.get("scd_type") or "") or None
    if scd and scd not in ("1", "2", "none"):
        scd = None

    confidence = str(answer.get("confidence") or "low")
    if confidence not in CONFIDENCE:
        confidence = "low"
    evidence = [str(e) for e in (answer.get("evidence_used") or []) if str(e).strip()]
    if not evidence:
        problems.append(f"{concept}: no evidence cited")
        return None, problems
    if not _evidence_is_grounded(evidence, item):
        problems.append(f"{concept}: cited evidence names nothing in the item it was given")
        return None, problems

    keep = {f"{t['source']}.{t['table']}" for t in item.get("candidate_tables") or []}
    chosen = [str(t) for t in (answer.get("tables") or []) if str(t) in keep] or sorted(keep)

    return {
        "core_class": item.get("core_class") or None,
        "grain": grain, "natural_key": key, "scd_type": scd, "tables": chosen,
        "confidence": confidence, "evidence_used": evidence,
    }, problems


# ---------------------------------------------------------------------------------------
# Rendering the proposal
# ---------------------------------------------------------------------------------------


def _q(text: str) -> str:
    return '"' + str(text).replace("\\", "\\\\").replace('"', "'") + '"'


def render_proposal(target: str, slug: str, accepted: Dict[str, Dict[str, Any]],
                    dropped: List[str]) -> str:
    lines = [
        f"# {target} proposed by a language model. NOT AN ARTIFACT — a staging file.",
        "#",
        f"# Written by `lm_propose.py --use-case {slug} --target {target} --apply`. Every",
        "# entry carries the confidence it was given and the evidence it cited. Nothing here",
        "# reaches a committed artifact until it is marked `reviewed: true` and promoted:",
        "#",
        f"#     python3 scripts/lm_propose.py --use-case {slug} --target {target} --review",
        f"#     python3 scripts/lm_propose.py --use-case {slug} --target {target} --promote",
        "#",
        "# A generated field is a proposal with a provenance, not a fact. Read the evidence",
        "# before marking one reviewed — that reading is the whole safeguard.",
        "",
        "version: 1",
        f"source: lm",
        "",
        f"{'columns' if target == 'annotations' else 'entities'}:",
    ]
    for name in sorted(accepted):
        entry = accepted[name]
        lines.append(f"  {name}:")
        lines.append("    reviewed: false")
        lines.append(f"    confidence: {entry['confidence']}")
        for ev in entry["evidence_used"]:
            lines.append(f"    # evidence: {ev}")
        if target == "annotations":
            lines.append(f"    role: {entry['role']}")
            if entry["additivity"]:
                lines.append(f"    additivity: {entry['additivity']}")
            if entry["unit"]:
                lines.append(f"    unit: {entry['unit']}")
            lines.append(f"    pii: {entry['pii']}")
            lines.append(f"    definition: {_q(entry['definition'])}")
            if entry["domain"]:
                lines.append("    domain:")
                lines.append("      closed: true")
                lines.append(f"      source: {_q(entry['domain']['source'])}")
                lines.append("      values:")
                for value in entry["domain"]["values"]:
                    lines.append(f"        - {value}")
        else:
            if entry["core_class"]:
                lines.append(f"    core_class: {entry['core_class']}")
            lines.append(f"    grain: {_q(entry['grain'])}")
            if entry["scd_type"]:
                lines.append(f"    scd_type: {entry['scd_type']}")
            lines.append("    natural_key:")
            for key in entry["natural_key"]:
                lines.append(f"      - {key}")
            lines.append("    sources:")
            for table in entry["tables"]:
                source, _, name_ = table.partition(".")
                lines.append(f"      - source: {source}")
                lines.append(f"        table: {name_}")
        lines.append("")
    if dropped:
        lines.append("# Dropped at validation, each for a stated reason. These are the")
        lines.append("# answers that would have been wrong quietly:")
        for reason in dropped:
            lines.append(f"#   {reason}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------------------


def promote(use_case: Path, slug: str, target: str, min_confidence: str,
            check: bool, source: str = "lm") -> Dict[str, Any]:
    """Merge reviewed entries into the hand-authored source file.

    Append-only, and it never touches an entry the file already has. The generated text is
    the same shape a human would have typed, with the provenance kept as a comment — so
    after promotion the artifact reads as one file with one convention, and `git log` is
    what says which lines a model drafted.
    """
    path = proposal_path(use_case, target, source)
    if not path.exists():
        return {"status": "skip", "reason": f"no {path.relative_to(REPO)} — run --apply first"}
    proposal = _miniyaml.load(path.read_text(encoding="utf-8")) or {}
    key = "columns" if target == "annotations" else "entities"
    entries = proposal.get(key) or {}
    # The file states its own provenance; the suffix only located it. Promoting under a
    # comment claiming a model wrote it would misrecord the only trace that survives.
    provenance = str(proposal.get("source") or source)

    target_name = ca.SOURCE if target == "annotations" else "taxonomy.yml"
    target_path = use_case / "ontology" / target_name
    existing_text = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
    existing = (_miniyaml.load(existing_text) or {}).get(key) or {} if existing_text else {}

    rank = {c: i for i, c in enumerate(CONFIDENCE)}
    promoted: List[str] = []
    held: List[str] = []
    for name in sorted(entries):
        entry = entries[name] or {}
        if not entry.get("reviewed"):
            held.append(f"{name}: not reviewed")
            continue
        if rank.get(str(entry.get("confidence")), 9) > rank[min_confidence]:
            held.append(f"{name}: confidence {entry.get('confidence')} below {min_confidence}")
            continue
        if name in existing:
            held.append(f"{name}: already decided in {target_name}")
            continue
        promoted.append(name)

    if not promoted:
        return {"status": "ok", "promoted": 0, "held": held,
                "artifact": str(target_path.relative_to(REPO))}

    block = [""]
    for name in promoted:
        entry = entries[name]
        block.append(f"  {name}:")
        block.append(f"    # promoted from proposals/{target}.{source}.yml "
                     f"({provenance}, confidence {entry.get('confidence')})")
        for field, value in entry.items():
            if field in ("reviewed", "confidence", "evidence_used"):
                continue
            if isinstance(value, list):
                block.append(f"    {field}:")
                for item in value:
                    if isinstance(item, dict):
                        first = True
                        for k, v in item.items():
                            block.append(f"      {'- ' if first else '  '}{k}: {v}")
                            first = False
                    else:
                        block.append(f"      - {item}")
            elif isinstance(value, dict):
                block.append(f"    {field}:")
                for k, v in value.items():
                    if isinstance(v, list):
                        block.append(f"      {k}:")
                        for item in v:
                            block.append(f"        - {item}")
                    else:
                        block.append(f"      {k}: {v if k == 'closed' else _q(v)}")
            else:
                block.append(f"    {field}: {_q(value) if field in ('definition', 'grain') else value}")
        block.append("")

    if not existing_text:
        header = [
            f"# {target_name} — hand-authored; nothing regenerates this file.",
            "#",
            "# Entries below marked `promoted from proposals/` were drafted by a language",
            "# model and reviewed before promotion. Everything else was written by hand.",
            "",
            "version: 1",
            "",
            f"{key}:",
        ]
        new_text = "\n".join(header + block) + "\n"
    else:
        new_text = existing_text.rstrip("\n") + "\n" + "\n".join(block) + "\n"

    if not check:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(new_text, encoding="utf-8")
    return {"status": "changed", "promoted": len(promoted), "names": promoted,
            "held": held, "artifact": str(target_path.relative_to(REPO))}


# ---------------------------------------------------------------------------------------
# Optional unattended backend
# ---------------------------------------------------------------------------------------


def run_anthropic(batch: Dict[str, Any], model: str) -> Dict[str, Any]:
    """Answer the batch without a human in the loop. Unavailable is not failed."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"status": "skip", "reason": "ANTHROPIC_API_KEY is not set"}
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return {"status": "skip", "reason": "the anthropic package is not installed "
                                            "(pip install anthropic)"}
    client = anthropic.Anthropic()
    prompt = (
        f"{batch['instructions']}\n\n"
        f"Items:\n{json.dumps(batch['items'], ensure_ascii=False, indent=2)}\n\n"
        "Reply with JSON only."
    )
    message = client.messages.create(
        model=model, max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"status": "fail", "reason": "the model returned no JSON object"}
    return {"status": "ok", "answers": json.loads(match.group(0)).get("answers") or []}


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------


def apply_answers(use_case: Path, slug: str, target: str, answers: List[Dict[str, Any]],
                  limit: Optional[int], check: bool) -> Dict[str, Any]:
    items = {i["id"]: i for i in build_batch(use_case, slug, target, limit)["items"]}
    validate = validate_annotation if target == "annotations" else validate_taxonomy

    accepted: Dict[str, Dict[str, Any]] = {}
    dropped: List[str] = []
    for answer in answers:
        name = str(answer.get("id") or "")
        item = items.get(name)
        if item is None:
            # Not pedantry: a hallucinated id is the cheapest possible signal that the
            # model answered from recall rather than from the batch it was handed.
            dropped.append(f"{name or '(no id)'}: not an item in this batch")
            continue
        entry, problems = validate(answer, item)
        dropped.extend(problems)
        if entry is not None:
            accepted[name] = entry

    path = proposal_path(use_case, target)
    content = render_proposal(target, slug, accepted, dropped)
    changed = (path.read_text(encoding="utf-8") if path.exists() else None) != content
    if changed and not check:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return {
        "status": "ok", "proposal": str(path.relative_to(REPO)), "changed": changed,
        "answered": len(answers), "accepted": len(accepted), "dropped": len(dropped),
        "drop_reasons": dropped[:20],
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Fill taxonomy and annotation fields with a language model, under review.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--use-case", required=True)
    p.add_argument("--target", choices=TARGETS, required=True)
    p.add_argument("--prepare", action="store_true", help="write the grounded question batch")
    p.add_argument("--apply", metavar="ANSWERS", help="ingest answers (JSON) into a proposal")
    p.add_argument("--review", action="store_true", help="show what is waiting to be reviewed")
    p.add_argument("--promote", action="store_true",
                   help="merge reviewed entries into the hand-authored source file")
    p.add_argument("--backend", choices=("agent", "anthropic"), default="agent",
                   help="agent: --prepare/--apply round trip (default). anthropic: unattended")
    p.add_argument("--model", default="claude-sonnet-5", help="model id for --backend anthropic")
    p.add_argument("--limit", type=int, help="cap the batch (highest-leverage items first)")
    p.add_argument("--min-confidence", choices=CONFIDENCE, default="medium",
                   help="lowest confidence --promote will accept")
    p.add_argument("--out", help="where --prepare writes the batch (default: stdout)")
    p.add_argument("--check", action="store_true", help="write nothing")
    p.add_argument("--format", choices=("text", "json"), default="text")
    args = p.parse_args(argv)

    use_case = use_case_dir(args.use_case)

    if args.promote:
        result = promote(use_case, args.use_case, args.target, args.min_confidence, args.check)
        if args.format == "json":
            print(json.dumps({"use_case": args.use_case, "target": args.target, **result},
                             ensure_ascii=False))
        elif result["status"] == "skip":
            print(f"skip: {result['reason']}")
        else:
            print(f"promoted {result['promoted']} entry(ies) into {result['artifact']}")
            for name in result.get("names", [])[:20]:
                print(f"  + {name}")
            for reason in result["held"][:10]:
                print(f"  held  {reason}")
        return 0

    if args.review:
        path = proposal_path(use_case, args.target)
        if not path.exists():
            print(f"skip: no {path.relative_to(REPO)} — run --prepare then --apply")
            return 0
        proposal = _miniyaml.load(path.read_text(encoding="utf-8")) or {}
        entries = proposal.get("columns" if args.target == "annotations" else "entities") or {}
        pending = {n: e for n, e in entries.items() if not (e or {}).get("reviewed")}
        if args.format == "json":
            print(json.dumps({"use_case": args.use_case, "target": args.target,
                              "total": len(entries), "pending": sorted(pending)},
                             ensure_ascii=False))
            return 0
        print(f"{len(entries)} proposed, {len(pending)} awaiting review "
              f"in {path.relative_to(REPO)}")
        for name in sorted(pending)[:30]:
            entry = pending[name] or {}
            summary = entry.get("definition") or entry.get("grain") or ""
            print(f"  {name:<28} {entry.get('confidence', '?'):<7} {str(summary)[:60]}")
        return 0

    if args.apply:
        payload = json.loads(Path(args.apply).read_text(encoding="utf-8"))
        answers = payload.get("answers") if isinstance(payload, dict) else payload
        result = apply_answers(use_case, args.use_case, args.target, answers or [],
                               args.limit, args.check)
        if args.format == "json":
            print(json.dumps({"use_case": args.use_case, "target": args.target, **result},
                             ensure_ascii=False))
        else:
            print(f"answered:  {result['answered']}")
            print(f"accepted:  {result['accepted']}")
            print(f"dropped:   {result['dropped']}")
            for reason in result["drop_reasons"]:
                print(f"  drop  {reason}")
            print(f"\n{'would write' if args.check else 'wrote'} {result['proposal']}")
        return 0

    batch = build_batch(use_case, args.use_case, args.target, args.limit)
    if args.backend == "anthropic":
        run = run_anthropic(batch, args.model)
        if run["status"] != "ok":
            print(json.dumps({"use_case": args.use_case, "target": args.target, **run},
                             ensure_ascii=False) if args.format == "json"
                  else f"skip: {run['reason']}")
            return 0
        result = apply_answers(use_case, args.use_case, args.target, run["answers"],
                               args.limit, args.check)
        print(json.dumps({"use_case": args.use_case, "target": args.target, **result},
                         ensure_ascii=False))
        return 0

    if not (args.prepare or args.out):
        p.error("one of --prepare, --apply, --review, or --promote is required")
    text = json.dumps(batch, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}: {batch['item_count']} item(s) for {args.target}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
