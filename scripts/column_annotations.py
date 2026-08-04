#!/usr/bin/env python3
"""Annotate what each conformed column *means*, so BI and agents can use it correctly.

`column-memory.json` records which raw column feeds which conformed column — the lineage.
Nothing records what the conformed column **is**, and three binding rules need exactly that:

    rule 11  additivity per measure — additive, semi-additive, or non-additive
    rule 17  PII declared at the source and tagged at every model that carries it
    rule 28  accepted_values on every column with a closed domain

Measured here before this existed: **272 conformed columns, 1 accepted_values test in the
whole project**, and nothing anywhere recording additivity or PII. The consequence is not
abstract. `wren/knowledge/rules/column-contracts.md` — the file an agent reads before
writing SQL — lists `QuantityInStock` beside `TotalToPay` as bare names, so the agent
cannot know that summing the first across time is wrong and summing the second is right,
or that `RecipientEmail` must not reach a shared dashboard.

**Annotations are facets, not a tree.** A column is several things at once: `TotalToPay` is
a measure *and* additive *and* currency-denominated *and* not PII. A single hierarchy has to
pick one of those to be the parent and loses the rest, so each column carries independent
facets — the poly-hierarchical shape, rather than the single-parent one.

**They belong to the conformed column, not to the model.** Conformance already asserts that
`ArticleNumber` means the same thing in Fortnox and Shopify, so annotating it once is both
cheaper and more correct than annotating each adapter: measured here, **272 decisions cover
952 (column, connector) pairs**. A per-model annotation would let the same column be a
measure in one connector and a dimension in another, which is precisely the drift the
conformed layer exists to prevent.

Three rules decide whether the output can be trusted:

- **An enum without a source is refused** (rule 5). A closed domain is a claim about an
  upstream system, and inventing its values produces a contract that passes every test and
  is wrong. The one enum this project had before this script — Shopify's `FinancialStatus`
  — names its source in the description; that is the standard.
- **A proposal is evidence, never a decision.** `--propose` derives candidates from cast
  types, name shapes, and existing `accepted_values` tests, each carrying what evidenced it
  and a confidence. Additivity is proposed at `low` confidence at best, because no schema
  contains it.
- **Abstain rather than guess.** A column the deriver cannot classify is emitted
  `abstained`, not defaulted. An inflated annotation is worse than an honest gap, because
  the gap gets filled and the guess gets trusted.

Usage:
    python3 scripts/column_annotations.py --use-case <slug> --propose   # candidates
    python3 scripts/column_annotations.py --use-case <slug>             # the artifact
    python3 scripts/column_annotations.py --use-case <slug> --check     # the CI gate
    python3 scripts/column_annotations.py --use-case <slug> --coverage  # what is unannotated
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _manifest import die  # noqa: E402
import _miniyaml  # noqa: E402
import _paths  # noqa: E402
from _paths import REPO  # noqa: E402

ARTIFACT = "column-annotations.json"
SOURCE = "annotations.yml"

# The facets. Independent by construction: a column takes one value from each, and no facet
# is a parent of another.
ROLES = ("identifier", "measure", "dimension", "timestamp", "flag", "text")
ADDITIVITY = ("additive", "semi_additive", "non_additive")
# The PII classes are the ones the annotation literature separates, and the separation is
# load-bearing: a direct identifier must be dropped or hashed, while a quasi-identifier is
# only re-identifying in combination, so the remedies differ.
PII_CLASSES = ("none", "direct", "quasi", "indirect")
UNITS = ("currency", "count", "quantity", "percent", "duration", "date", "none")
CONFIDENCE = ("high", "medium", "low")

# Warehouse cast type -> the role it evidences. Types are evidence, never a verdict: a
# FLOAT64 is usually a measure and is a dimension when it is a rate somebody groups by.
TYPE_ROLE = {
    "float64": "measure", "numeric": "measure", "bignumeric": "measure",
    "int64": "measure", "integer": "measure",
    "boolean": "flag", "bool": "flag",
    "date": "timestamp", "datetime": "timestamp", "timestamp": "timestamp",
    "string": "dimension",
}

# Name shapes. High recall on purpose — a proposal a human rejects costs a keystroke, and a
# PII column nobody flagged costs a disclosure.
NAME_SHAPES: Tuple[Tuple[re.Pattern, str, str], ...] = (
    (re.compile(r"(^|[a-z])(Id|Number|No|Code|Key)$"), "identifier", "name ends in an identifier suffix"),
    (re.compile(r"^(is|has|Is|Has)[A-Z]"), "flag", "name reads as a boolean predicate"),
    (re.compile(r"(Date|At|Time|Timestamp)$"), "timestamp", "name ends in a temporal suffix"),
    (re.compile(r"(Total|Amount|Price|Sum|Cost|Balance|Net|Discount|VAT|Quantity)"), "measure",
     "name contains an amount or quantity word"),
    (re.compile(r"(Name|Description|Comment|Note|Text|Label)$"), "text", "name ends in a free-text suffix"),
)

# Direct identifiers name a person on their own; quasi-identifiers re-identify only in
# combination. Both are reported, with the class, because the remedies are different.
PII_SHAPES: Tuple[Tuple[re.Pattern, str, str], ...] = (
    (re.compile(r"(Email|Mail)", re.I), "direct", "an email address identifies a person directly"),
    (re.compile(r"(Phone|Mobile|Tel)", re.I), "direct", "a telephone number identifies a person directly"),
    (re.compile(r"(Ssn|PersonalNumber|Personnummer|NationalId|Passport)", re.I), "direct",
     "a national identity number identifies a person directly"),
    (re.compile(r"(Iban|Bankgiro|Plusgiro|AccountNumber|Bic|Swift)", re.I), "direct",
     "a bank identifier is directly identifying and financially sensitive"),
    (re.compile(r"(Address\d?$|Address[12]$|Street|ZipCode|PostalCode)", re.I), "quasi",
     "a street address re-identifies in combination with other fields"),
    (re.compile(r"(BirthDate|DateOfBirth|Birthday)", re.I), "quasi",
     "a date of birth re-identifies in combination with other fields"),
    (re.compile(r"^(ContactPerson|OurReference|YourReference|DeliveryName|InvoiceName)"), "quasi",
     "a named contact re-identifies in combination with other fields"),
)

# A measure whose name says it is a level rather than a flow. Semi-additive means it may be
# summed across every dimension except time — a stock balance at two dates does not add.
SEMI_ADDITIVE_SHAPES = re.compile(
    r"(Balance|QuantityInStock|StockGoods|InStock|OnHand|Level|Headcount)", re.I
)
# Ratios and rates. Storing them is what rule 11 forbids, so proposing one is also a finding.
NON_ADDITIVE_SHAPES = re.compile(r"(Rate|Percent|Percentage|Ratio|Average|Avg|Margin)", re.I)

PLACEHOLDER = re.compile(r"(?i)\b(todo|tbd|fixme|xxx|\(placeholder\))\b")


def use_case_dir(slug: str) -> Path:
    """`_paths.require_use_case_dir` bound to this module's REPO; absence exits 2."""
    return _paths.require_use_case_dir(slug, REPO)


# ---------------------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------------------


def conformed_columns(use_case: Path) -> Dict[str, Dict[str, Any]]:
    """Every conformed column, with the concepts and connectors that carry it.

    Read from `column-memory.json` rather than from the manifest because that artifact is
    already the answer to "which columns are conformed", and recomputing it here would give
    this script its own opinion about a fact the repository has settled.
    """
    path = use_case / "ontology" / "column-memory.json"
    if not path.exists():
        return {}
    memory = json.loads(path.read_text(encoding="utf-8"))
    out: Dict[str, Dict[str, Any]] = {}
    for contract in memory.get("contracts", []) or []:
        concept = contract.get("concept")
        for column in contract.get("columns", []) or []:
            name = column.get("column")
            if not name:
                continue
            row = out.setdefault(name, {"concepts": set(), "connectors": set()})
            row["concepts"].add(concept)
            row["connectors"].update(column.get("carried_by") or [])
    return {
        name: {"concepts": sorted(row["concepts"]), "connectors": sorted(row["connectors"])}
        for name, row in sorted(out.items())
    }


def cast_types(project: Path) -> Dict[str, Set[str]]:
    """The warehouse type each conformed column is cast to, harvested from the models.

    The staging layer casts every column explicitly — `cast(o.total_price as float64)
    TotalToPay` — so the project states its own types without a warehouse, a `dbt docs
    generate`, or a catalog. Where two connectors cast the same column differently, both
    types are kept: that disagreement is itself worth seeing.
    """
    types: Dict[str, Set[str]] = {}
    if not project.exists():
        return types
    for path in project.rglob("*.sql"):
        if "/target/" in path.as_posix():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover - unreadable file is a project defect
            continue
        for column, dtype in _scan_casts(text):
            types.setdefault(column, set()).add(dtype)
    return types


_CAST_TAIL = re.compile(r"^\s*\)\s*(?:as\s+)?([A-Za-z_]\w*)", re.I)


def _scan_casts(sql: str) -> List[Tuple[str, str]]:
    """`(column, type)` for every `cast(... as TYPE) Alias`, parentheses balanced.

    A regex cannot do this. `cast(nullif(c.city,'') as string) City` is the ordinary form in
    this project — a cast wrapping a function — and a `[^()]*` body stops at the inner
    paren, so a pattern that reads the simple case silently loses every wrapped one. That is
    the worst shape for a bug here: type evidence just goes missing, columns abstain for no
    stated reason, and the output still looks complete.
    """
    out: List[Tuple[str, str]] = []
    for match in re.finditer(r"\bcast\s*\(", sql, re.I):
        depth, i = 1, match.end()
        while i < len(sql) and depth:
            if sql[i] == "(":
                depth += 1
            elif sql[i] == ")":
                depth -= 1
                if not depth:
                    break
            i += 1
        if depth:  # unbalanced — a truncated file, not something to guess at
            continue
        body = sql[match.end():i]
        as_match = re.search(r"\bas\s+(\w+)\s*$", body, re.I)
        tail = _CAST_TAIL.match(sql[i:])
        if as_match and tail:
            out.append((tail.group(1), as_match.group(1).lower()))
    return out


def declared_definitions(project: Path) -> Dict[str, str]:
    """Column descriptions the project already wrote, harvested as candidate definitions.

    A definition is the one annotation field a schema cannot evidence, so the alternative
    to harvesting is inventing 272 of them — the failure rule 5 names. 97 columns here
    already carry one, several of them domain facts nobody should be paraphrasing:
    `AccountNumber` is documented as "BAS account number, consists of four digits". Reusing
    the project's own words keeps the annotation and the dbt docs from drifting into two
    descriptions of one column.

    First description wins. Two connectors describing the same conformed column differently
    is a real disagreement, and picking one silently would hide it — the reviewer sees the
    first and can correct it against the second.
    """
    out: Dict[str, str] = {}
    if not project.exists():
        return out
    for path in sorted(project.rglob("schema.yml")):
        if "/target/" in path.as_posix():
            continue
        try:
            data = _miniyaml.load(path.read_text(encoding="utf-8")) or {}
        except Exception:  # pragma: no cover - malformed yml is a project defect
            continue
        for model in data.get("models", []) or []:
            for column in model.get("columns", []) or []:
                name, text = column.get("name"), str(column.get("description") or "").strip()
                if name and text and str(name) not in out:
                    out[str(name)] = " ".join(text.split())
    return out


def declared_domains(project: Path) -> Dict[str, Dict[str, Any]]:
    """Closed domains the project already declares, as `accepted_values` tests.

    These are the only enum values in the repository that are *evidenced* rather than
    recalled, so they are harvested rather than restated. Shopify's `FinancialStatus` is the
    worked example: seven values, and a description naming the API that defines them.
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not project.exists():
        return out
    for path in sorted(project.rglob("schema.yml")):
        if "/target/" in path.as_posix():
            continue
        try:
            data = _miniyaml.load(path.read_text(encoding="utf-8")) or {}
        except Exception:  # pragma: no cover - malformed yml is a project defect
            continue
        for model in data.get("models", []) or []:
            for column in model.get("columns", []) or []:
                name = column.get("name")
                for test in column.get("data_tests", []) or column.get("tests", []) or []:
                    if not isinstance(test, dict) or "accepted_values" not in test:
                        continue
                    values = (test["accepted_values"] or {}).get("values") or []
                    if name and values:
                        out[str(name)] = {
                            "values": [str(v) for v in values],
                            "declared_in": path.relative_to(REPO).as_posix()
                            if path.is_relative_to(REPO) else str(path),
                            "description": str(column.get("description") or "").strip(),
                        }
    return out


# ---------------------------------------------------------------------------------------
# Proposing
# ---------------------------------------------------------------------------------------


def derive(name: str, types: Set[str], domain: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Facet candidates for one column, each carrying the evidence that produced it.

    Order matters: a declared domain outranks a name shape, and a name shape outranks a
    cast type. `OrderNumber` is an int64 and an identifier, not a measure — summing it is
    meaningless — so the identifier suffix has to win over the numeric type.
    """
    evidence: List[str] = []
    role: Optional[str] = None
    confidence = "low"

    if domain:
        role, confidence = "dimension", "high"
        evidence.append(f"declared accepted_values in {domain['declared_in']}")

    if role is None:
        for pattern, shaped, why in NAME_SHAPES:
            if pattern.search(name):
                role, confidence = shaped, "medium"
                evidence.append(why)
                break

    type_role = next((TYPE_ROLE[t] for t in sorted(types) if t in TYPE_ROLE), None)
    if type_role:
        evidence.append(f"cast to {'/'.join(sorted(types))}")
        if role is None:
            role, confidence = type_role, "medium" if len(types) == 1 else "low"
        elif role == type_role:
            confidence = "high" if confidence != "low" else "medium"
        elif role == "measure" and type_role in ("dimension", "text"):
            # A name says amount, the warehouse says string. One of them is wrong, and
            # guessing which produces a measure nobody can sum or a dimension nobody can
            # group. Abstain and say so.
            evidence.append(f"CONFLICT: name suggests measure, cast is {'/'.join(sorted(types))}")
            role, confidence = None, "low"

    additivity: Optional[str] = None
    if role == "measure":
        if NON_ADDITIVE_SHAPES.search(name):
            additivity = "non_additive"
            evidence.append("name reads as a rate or ratio — rule 11 forbids storing it as a fact column")
        elif SEMI_ADDITIVE_SHAPES.search(name):
            additivity = "semi_additive"
            evidence.append("name reads as a level rather than a flow; it does not add across time")
        # Additive is never proposed. It is the default a reader would assume, so proposing
        # it adds no information and removes the prompt to actually decide (rule 11).

    pii, pii_why = "none", ""
    for pattern, cls, why in PII_SHAPES:
        if pattern.search(name):
            pii, pii_why = cls, why
            break
    if pii != "none":
        evidence.append(pii_why)

    unit: Optional[str] = None
    if role == "measure":
        unit = "quantity" if re.search(r"Quantity|Stock|Count", name, re.I) else "currency"
        evidence.append(f"unit proposed as {unit} from the name")
    elif role == "timestamp":
        unit = "date"

    return {
        "role": role,
        "additivity": additivity,
        "pii": pii,
        "unit": unit,
        "domain": ({"closed": True, "values": domain["values"],
                    "source": domain["description"] or domain["declared_in"]}
                   if domain else None),
        "confidence": confidence if role else "low",
        "abstained": role is None,
        "evidence": evidence,
    }


def propose(use_case: Path, existing: Dict[str, Any]) -> Dict[str, Any]:
    """Candidates for every conformed column no one has annotated yet."""
    columns = conformed_columns(use_case)
    project = use_case / "dbt_project"
    types = cast_types(project)
    domains = declared_domains(project)
    definitions = declared_definitions(project)

    decided = set(existing.get("columns") or {})
    proposed: Dict[str, Any] = {}
    abstained: List[str] = []
    for name, meta in columns.items():
        if name in decided:
            continue
        candidate = derive(name, types.get(name, set()), domains.get(name))
        candidate["definition"] = definitions.get(name, "")
        candidate["concepts"] = meta["concepts"]
        candidate["connectors"] = meta["connectors"]
        proposed[name] = candidate
        if candidate["abstained"]:
            abstained.append(name)

    return {
        "proposed": proposed,
        "abstained": sorted(abstained),
        "already_annotated": len(decided),
        "conformed_columns": len(columns),
        "declared_domains": sorted(domains),
        "harvested_definitions": sum(
            1 for c in proposed.values() if c.get("definition")
        ),
    }


def render_stub(proposal: Dict[str, Any], slug: str) -> str:
    """An `annotations.yml` a human finishes.

    Ordered by leverage — the columns the most connectors carry first — because a reviewer
    who stops halfway should have spent that time on the columns that matter most.
    """
    lines = [
        "# What each conformed column MEANS. HAND-AUTHORED; nothing regenerates this file.",
        "#",
        f"# Scaffolded by `column_annotations.py --use-case {slug} --propose`. Every value",
        "# below is derived from a cast type, a name shape, or a declared accepted_values",
        "# test — evidence, not a decision. Confirm each one. Then run:",
        "#",
        f"#     python3 scripts/column_annotations.py --use-case {slug}",
        "#",
        f"# role:       {' | '.join(ROLES)}",
        f"# additivity: {' | '.join(ADDITIVITY)}   (measures only — rule 11)",
        f"# pii:        {' | '.join(PII_CLASSES)}   (rule 17)",
        f"# unit:       {' | '.join(UNITS)}",
        "#",
        "# A `domain:` block MUST name its source. An enum nobody can cite is invented",
        "# (rule 5), and a wrong closed domain passes every test.",
        "",
        "version: 1",
        "",
        "columns:",
    ]
    ordered = sorted(
        proposal["proposed"].items(),
        key=lambda kv: (-len(kv[1]["connectors"]), kv[0]),
    )
    for name, cand in ordered:
        lines.append(f"  {name}:")
        lines.append(f"    # carried by {len(cand['connectors'])} connector(s): "
                     f"{', '.join(cand['connectors']) or 'none'}")
        for why in cand["evidence"]:
            lines.append(f"    # evidence: {why}")
        if cand["abstained"]:
            lines.append("    # ABSTAINED — nothing evidenced a role. Classify it by hand.")
        lines.append(f"    role: {cand['role'] or ''}")
        if cand["role"] == "measure":
            lines.append(f"    additivity: {cand['additivity'] or ''}"
                         f"   # required for a measure (rule 11)")
        if cand["unit"]:
            lines.append(f"    unit: {cand['unit']}")
        lines.append(f"    pii: {cand['pii']}")
        if cand.get("definition"):
            escaped = cand["definition"].replace('"', "'")
            lines.append(f'    definition: "{escaped}"'
                         f"   # harvested from the project's own schema.yml")
        else:
            lines.append('    definition: ""   # nothing described this column — write it')
        if cand["domain"]:
            lines.append("    domain:")
            lines.append("      closed: true")
            lines.append(f"      source: \"{cand['domain']['source']}\"")
            lines.append("      values:")
            for value in cand["domain"]["values"]:
                lines.append(f"        - {value}")
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------------------


def build(use_case: Path, slug: str, source: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    columns = conformed_columns(use_case)
    problems: List[str] = []
    annotated: List[Dict[str, Any]] = []

    for name in sorted(source.get("columns") or {}):
        entry = (source["columns"] or {})[name] or {}
        if name not in columns:
            problems.append(
                f"{name}: annotated but no conformed column by that name — the column was "
                f"renamed or removed, and the annotation now describes nothing"
            )
            continue
        role = str(entry.get("role") or "")
        if role not in ROLES:
            problems.append(f"{name}: role {role or '(empty)'!r} is not one of {', '.join(ROLES)}")
            continue

        additivity = str(entry.get("additivity") or "") or None
        if role == "measure" and additivity not in ADDITIVITY:
            problems.append(
                f"{name}: a measure must declare additivity (rule 11) — one of "
                f"{', '.join(ADDITIVITY)}. A measure true at a coarser grain double-counts "
                f"while every test passes"
            )
        if additivity and role != "measure":
            problems.append(f"{name}: additivity is meaningless on a {role}")

        pii = str(entry.get("pii") or "none")
        if pii not in PII_CLASSES:
            problems.append(f"{name}: pii {pii!r} is not one of {', '.join(PII_CLASSES)}")

        definition = str(entry.get("definition") or "").strip()
        if not definition:
            problems.append(f"{name}: no definition — a facet set without one says how to "
                            f"compute the column, never what it means")
        elif PLACEHOLDER.search(definition):
            problems.append(f"{name}: definition is a placeholder ({definition[:40]!r})")

        domain = entry.get("domain") or None
        if domain:
            values = [str(v) for v in (domain.get("values") or [])]
            if not values:
                problems.append(f"{name}: domain declared closed with no values")
            if not str(domain.get("source") or "").strip():
                problems.append(
                    f"{name}: closed domain with no source. An enum nobody can cite is "
                    f"invented (rule 5), and a wrong one passes every test"
                )
            domain = {"closed": bool(domain.get("closed", True)),
                      "values": values, "source": str(domain.get("source") or "")}

        annotated.append({
            "column": name,
            "role": role,
            "additivity": additivity,
            "unit": str(entry.get("unit") or "") or None,
            "pii": pii,
            "definition": definition,
            "domain": domain,
            "concepts": columns[name]["concepts"],
            "connectors": columns[name]["connectors"],
            "carried_by_count": len(columns[name]["connectors"]),
        })

    covered = {a["column"] for a in annotated}
    unannotated = sorted(set(columns) - covered)
    by_role: Dict[str, int] = {}
    for row in annotated:
        by_role[row["role"]] = by_role.get(row["role"], 0) + 1

    model = {
        "use_case": slug,
        "generated_by": "scripts/column_annotations.py",
        "normative_source": "ontology/annotations.yml; the conformed columns come from "
                            "ontology/column-memory.json",
        "facets": {
            "role": list(ROLES), "additivity": list(ADDITIVITY),
            "pii": list(PII_CLASSES), "unit": list(UNITS),
        },
        "provenance": {
            # Committed inputs only — nothing run-dependent, or `--check` is permanently red.
            "conformed_columns": len(columns),
            "annotated": len(annotated),
            "unannotated": len(unannotated),
            "by_role": dict(sorted(by_role.items())),
            "pii_columns": sum(1 for a in annotated if a["pii"] != "none"),
            "closed_domains": sum(1 for a in annotated if a["domain"]),
        },
        "columns": annotated,
        "unannotated": unannotated,
    }
    return model, problems


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Annotate what each conformed column means (role, additivity, PII, domain).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--use-case", required=True)
    p.add_argument("--propose", action="store_true",
                   help="scaffold ontology/annotations.yml; refuses to overwrite")
    p.add_argument("--coverage", action="store_true", help="report what is not annotated yet")
    p.add_argument("--check", action="store_true", help="exit 1 if stale or invalid")
    p.add_argument("--format", choices=("text", "json"), default="text")
    args = p.parse_args(argv)

    use_case = use_case_dir(args.use_case)
    ontology = use_case / "ontology"
    columns = conformed_columns(use_case)
    if not columns:
        payload = {"use_case": args.use_case, "status": "skip",
                   "reason": "no ontology/column-memory.json — run dbt_column_memory.py --write"}
        print(json.dumps(payload, ensure_ascii=False) if args.format == "json"
              else f"skip: {payload['reason']}")
        return 0

    source_path = ontology / SOURCE
    source = (_miniyaml.load(source_path.read_text(encoding="utf-8")) or {}) \
        if source_path.exists() else {}

    if args.propose:
        proposal = propose(use_case, source)
        if source_path.exists():
            print(
                f"REFUSED: {source_path.relative_to(REPO)} already exists. A derived "
                f"candidate must never overwrite a confirmed annotation.\n"
                f"  Delete it to re-scaffold, or edit it by hand.",
                file=sys.stderr,
            )
            return 1
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(render_stub(proposal, args.use_case), encoding="utf-8")
        if args.format == "json":
            print(json.dumps({"use_case": args.use_case,
                              "written": str(source_path.relative_to(REPO)),
                              "proposed": len(proposal["proposed"]),
                              "abstained": proposal["abstained"],
                              "declared_domains": proposal["declared_domains"]},
                             ensure_ascii=False))
        else:
            print(f"scaffolded {source_path.relative_to(REPO)}")
            print(f"  {len(proposal['proposed'])} column(s) proposed, "
                  f"{len(proposal['abstained'])} abstained")
            print(f"  {len(proposal['declared_domains'])} closed domain(s) harvested from "
                  f"existing accepted_values tests")
            print(f"  {proposal['harvested_definitions']} definition(s) harvested from "
                  f"existing column descriptions")
            print("\nEvery value is evidence, not a decision. Confirm each, and write the "
                  "definitions.")
        return 0

    if args.coverage:
        annotated = set(source.get("columns") or {})
        missing = sorted(set(columns) - annotated)
        ranked = sorted(missing, key=lambda c: (-len(columns[c]["connectors"]), c))
        if args.format == "json":
            print(json.dumps({"use_case": args.use_case, "conformed": len(columns),
                              "annotated": len(annotated), "unannotated": len(missing),
                              "highest_leverage": ranked[:20]}, ensure_ascii=False))
            return 0
        print(f"conformed: {len(columns)}   annotated: {len(annotated)}   "
              f"unannotated: {len(missing)}")
        for name in ranked[:20]:
            print(f"  {name:<28} carried by {len(columns[name]['connectors'])} connector(s)")
        return 0

    if not source:
        payload = {"use_case": args.use_case, "status": "skip",
                   "reason": f"no ontology/{SOURCE} — run --propose first"}
        print(json.dumps(payload, ensure_ascii=False) if args.format == "json"
              else f"skip: {payload['reason']}")
        return 0

    model, problems = build(use_case, args.use_case, source)
    target = ontology / ARTIFACT
    content = json.dumps(model, indent=2, ensure_ascii=False) + "\n"
    existing = target.read_text(encoding="utf-8") if target.exists() else None
    changed = existing != content
    if changed and not args.check:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    prov = model["provenance"]
    if args.format == "json":
        print(json.dumps({
            "use_case": args.use_case,
            "artifact": str(target.relative_to(REPO)),
            "changed": changed,
            **prov,
            "problems": problems,
        }, ensure_ascii=False))
        return 1 if problems or (args.check and changed) else 0

    print(f"use-case:   {args.use_case}")
    print(f"annotated:  {prov['annotated']} of {prov['conformed_columns']} conformed column(s)")
    print(f"roles:      {prov['by_role']}")
    print(f"pii:        {prov['pii_columns']} column(s) carry personal data")
    print(f"domains:    {prov['closed_domains']} closed domain(s)")
    if problems:
        print(f"\nproblems ({len(problems)}):")
        for problem in problems:
            print(f"  {problem}")
    if args.check:
        if changed:
            print(f"\n{target.relative_to(REPO)} is stale — run without --check")
            return 1
        if not problems:
            print("\nAnnotations are current.")
    elif changed:
        print(f"\nwrote {target.relative_to(REPO)}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
