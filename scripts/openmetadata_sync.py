#!/usr/bin/env python3
"""Project this repository's derived metadata into OpenMetadata — the discovery tier.

OpenMetadata is the human-facing catalog over the same dbt use-cases WrenAI and
Lightdash serve. The pipeline is **unidirectional**: git is the source of truth, the
catalog is a destination, and nothing here ever reads a description or a tag back out
of the server and writes it into the repository. See docs/OPENMETADATA_INTEGRATION.md.

Two phases, and keeping them apart is the whole design:

    emit    (default, offline, deterministic)   ->  <use-case>/openmetadata/
    push    (--push, network, explicit)         ->  the bundle, PUT at a server

The bundle is a committed artifact, exactly like `wren/` and `lightdash/knowledge/`,
so `--check` is a real gate rather than a note saying the gate could not run. A stage
whose only verification is "it reached a server nobody has" is a stage CI cannot hold.

What this bridge writes, and what it deliberately does not
---------------------------------------------------------

**It never creates a Table entity.** `openmetadata-ingestion[dbt]` already builds
tables, descriptions, owners, dbt tests, and model-level lineage out of
manifest/catalog/run_results — that is what the connector is for, and what
open-metadata/openmetadata-dbt-action runs in CI. Re-deriving tables here would be a
second source of truth fighting the connector field by field on every ingest. So the
mechanical layer is handed back to upstream as a generated workflow config
(`ingestion/dbt.yaml`, run with `metadata ingest -c`), and this bridge owns only what
dbt cannot say. Same rule as the Wren bridge ("enriches, never duplicates") and the
Lightdash bridge ("never writes a metric").

| Bundle file | Holds | Derived from |
| --- | --- | --- |
| `ingestion/dbt.yaml` | upstream's dbt connector workflow | manifest/catalog/run_results paths |
| `bundle/glossary.json` | one glossary; concept and column terms | `index.json`, `column-annotations.json` |
| `bundle/classifications.json` | classifications + tags for every facet | `column-annotations.json` `facets` |
| `bundle/tag-applications.json` | which tag lands on which column FQN | annotations + the manifest |
| `bundle/column-lineage.json` | `AddLineageRequest` per table pair | `column-memory.json` bindings |
| `bundle/dlt-provenance.json` | dlt's load columns and system tables | declared columns / a dlt warehouse |
| `rdf/openmetadata-alignment.ttl` | our topology in OpenMetadata's own RDF vocabulary | `index.json` + the ontology |
| `knowledge/*.md` | what an agent reads before asking the catalog | everything above |

Five refusals, each of which is a way the catalog would read as authoritative while
being wrong:

- **The service name is declared, never derived** (rule 5). An OpenMetadata table FQN
  is `service.database.schema.table`, and `service` is a fact about the server — which
  database service the warehouse was registered under — that appears nowhere in
  `manifest.json`. Guessing it produces a bundle whose every FQN resolves to nothing:
  the push 404s on the lucky day and silently attaches lineage to a same-named service
  on the unlucky one. No `openmetadata.yml` means skip, with the file to write named.
- **An endpoint that resolves to no dbt node is dropped and counted.** Column lineage
  is parsed SQL, and a parse yields names that are not relations — `NULL`, an unnest
  alias, a struct field. Measured on enhanza-analytics: 87 of 92 distinct
  `source_model` values resolve to a manifest node; the other 5 are parse artifacts
  and are reported, never emitted as edges to invented tables.
- **`PII.None` is not written.** `PII.Sensitive` and `PII.NonSensitive` are
  OpenMetadata system tags; a third one is not, and inventing a tag name means the
  push creates a classification member nobody governs. `pii: direct` maps to
  `PII.Sensitive`; `quasi` and `indirect` get `ColumnPII.*` tags of our own, because
  folding them into `NonSensitive` would state the opposite of what the annotation says.
- **An unannotated column gets no tag.** 183 of enhanza's 272 conformed columns are
  unannotated. Tagging them `Additive` by default would put a number in a BI tool that
  nobody decided was summable — the exact defect `column-annotations.json` exists to
  prevent.
- **Push is never implicit.** `--push` is required, both env vars must be set, and the
  `openmetadata` sync stage never passes it. Egress is a human decision every time.

Dependencies
------------

Emitting needs the standard library only. Two optional packages sharpen it, the same
shape as sqlglot in `dbt_column_lineage.py`:

- `openmetadata-ingestion` — used to **validate** the emitted payloads against the
  server's own generated pydantic models, and to run the dbt workflow config. Not used
  as a client: its wheel must match the server version exactly (see
  open-metadata/openmetadata-dbt-action), and a bridge that hard-depends on that pin
  breaks on every server upgrade. Absent, validation reports `skip`.
- `duckdb` — reads a dlt-loaded warehouse's real schema for the provenance bundle.
  Absent, dlt columns are still found in whatever the dbt project declares.

The push itself is `urllib` against the documented REST API, so it has no dependency
at all and cannot drift from a pinned wheel.

Usage:
    python3 scripts/openmetadata_sync.py --use-case <slug>
    python3 scripts/openmetadata_sync.py --use-case <slug> --check
    python3 scripts/openmetadata_sync.py --use-case <slug> --push        # egress
    python3 scripts/openmetadata_sync.py --use-case <slug> --push --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _miniyaml  # noqa: E402
import _paths  # noqa: E402
from _manifest import Manifest  # noqa: E402

REPO = _paths.REPO

CONFIG_NAME = "openmetadata.yml"
BUNDLE_DIR = "openmetadata"

SERVER_URL_ENV = "OPENMETADATA_SERVER_URL"
AUTH_TOKEN_ENV = "OPENMETADATA_AUTH_TOKEN"
SERVICE_ENV = "OPENMETADATA_DB_SERVICE"

# The `openmetadata-ingestion` wheel must match the server version exactly — the
# constraint open-metadata/openmetadata-dbt-action states in its own README
# (`OPENMETADATA_VERSION` must equal the server's). The wheel carries a fourth
# component the server tag does not: server `1.13.3-release` is wheel `1.13.3.0`.
# Named here so a skip can print the install line rather than "install the package",
# and so upgrading is one edit rather than a search.
SERVER_PIN = "1.13.3"
INGESTION_PIN = f"{SERVER_PIN}.0"
INGESTION_INSTALL = f"pip install 'openmetadata-ingestion[dbt]=={INGESTION_PIN}'"

# `lineageDetails.source` is a closed enum in the OpenMetadata spec
# (openmetadata-spec/.../type/entityLineage.json). DbtLineage is the honest member:
# every edge below is derived from dbt's manifest, whether via the DAG or via sqlglot
# over the `raw_code` the manifest carries.
LINEAGE_SOURCE = "DbtLineage"


def use_case_dir(slug: str) -> Optional[Path]:
    """`_paths.use_case_dir` bound to this module's REPO, which tests override."""
    return _paths.use_case_dir(slug, REPO)


def _header(slug: str) -> str:
    return (
        "<!-- Generated by scripts/openmetadata_sync.py — do not hand-edit.\n"
        f"     Regenerate: python3 scripts/use_case_sync.py --use-case {slug} "
        "--stage openmetadata -->\n"
    )


# ---------------------------------------------------------------------------------------
# Fully qualified names
# ---------------------------------------------------------------------------------------


def fqn_part(part: str) -> str:
    """Quote one FQN component the way OpenMetadata's FQN grammar requires.

    A component containing a dot would otherwise split the FQN into the wrong number
    of levels — `service.db.schema.my.table` reads as five components, and the table
    is never found. Quoting is not cosmetic here.
    """
    if "." in part or '"' in part:
        return '"' + part.replace('"', '""') + '"'
    return part


def fqn(*parts: str) -> str:
    return ".".join(fqn_part(p) for p in parts if p is not None and p != "")


# ---------------------------------------------------------------------------------------
# Configuration — declared, never derived
# ---------------------------------------------------------------------------------------


@dataclass
class Config:
    """`<use-case>/openmetadata.yml`. Hand-authored, like `ontology/connectors.yml`."""

    service: str
    glossary: str
    glossary_display_name: str
    database_override: Optional[str] = None
    schema_override: Optional[str] = None
    dlt_warehouse: Optional[str] = None
    dlt_schema: Optional[str] = None
    tags_enabled: bool = True

    @classmethod
    def load(cls, use_case: Path, slug: str) -> Tuple[Optional["Config"], str]:
        """(config, reason-if-absent). The env var is an override, never a default.

        `service` has no derivable value: it names a database service registered on the
        server, and nothing in the dbt project knows it. Env-only would work for a
        single deployment and silently mis-target the moment two use-cases point at two
        services, so the file is the source of truth and the env var overrides it.
        """
        path = use_case / CONFIG_NAME
        data: Dict[str, Any] = {}
        if path.exists():
            parsed = _miniyaml.load(path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                data = parsed
        service = os.environ.get(SERVICE_ENV) or data.get("service")
        if not service:
            if not path.exists():
                return None, (
                    f"no {CONFIG_NAME} — declare the OpenMetadata database service this "
                    f"use-case's warehouse is registered under (or set {SERVICE_ENV})"
                )
            return None, (
                f"{CONFIG_NAME} declares no `service:` — it names the OpenMetadata "
                f"database service, which no dbt artifact knows (or set {SERVICE_ENV})"
            )
        return cls(
            service=str(service),
            glossary=str(data.get("glossary") or slug),
            glossary_display_name=str(data.get("glossary_display_name") or slug),
            database_override=data.get("database"),
            schema_override=data.get("schema"),
            dlt_warehouse=data.get("dlt_warehouse"),
            dlt_schema=data.get("dlt_schema"),
            tags_enabled=bool(data.get("tags", True)),
        ), ""


# ---------------------------------------------------------------------------------------
# dbt node -> warehouse relation
# ---------------------------------------------------------------------------------------


@dataclass
class Relation:
    """One warehouse relation, and the dbt node that produced it."""

    database: str
    schema: str
    table: str
    unique_id: str
    resource_type: str

    def table_fqn(self, cfg: Config) -> str:
        return fqn(
            cfg.service,
            cfg.database_override or self.database,
            cfg.schema_override or self.schema,
            self.table,
        )

    def column_fqn(self, cfg: Config, column: str) -> str:
        return fqn(
            cfg.service,
            cfg.database_override or self.database,
            cfg.schema_override or self.schema,
            self.table,
            column,
        )


def _relation_of(node: Dict[str, Any]) -> Optional[Relation]:
    """dbt's own relation for a node, from `relation_name` when it carries one.

    `relation_name` is what dbt actually compiled into the SQL — already quoted,
    already resolved through aliases, custom schemas, and `generate_schema_name`.
    Composing `database.schema.alias` by hand reproduces that logic and gets it wrong
    for every project that overrides the macro, which is most real ones.
    """
    rel = node.get("relation_name")
    if isinstance(rel, str) and rel:
        parts = _split_relation(rel)
        if len(parts) == 3:
            database, schema, table = parts
            return Relation(
                database, schema, table, node.get("unique_id", ""),
                node.get("resource_type", ""),
            )
    database = node.get("database")
    schema = node.get("schema")
    table = node.get("identifier") or node.get("alias") or node.get("name")
    if not (database and schema and table):
        return None
    return Relation(
        str(database), str(schema), str(table), node.get("unique_id", ""),
        node.get("resource_type", ""),
    )


def _split_relation(rel: str) -> List[str]:
    """Split `"db"."schema"."table"` honouring quotes, since a part may contain a dot."""
    parts: List[str] = []
    current: List[str] = []
    quoted = False
    index = 0
    while index < len(rel):
        char = rel[index]
        if char == '"':
            if quoted and index + 1 < len(rel) and rel[index + 1] == '"':
                current.append('"')
                index += 2
                continue
            quoted = not quoted
        elif char == "." and not quoted:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    parts.append("".join(current))
    return [p for p in parts if p != ""]


def relation_index(man: Manifest) -> Dict[str, Relation]:
    """Every name a `column-memory.json` binding might use, mapped to its relation.

    Bindings name their endpoints the way the SQL did: a model by its dbt name, a
    source by `<source_name>__<table>` (the staging convention this project's resolver
    reproduces). Both are registered, and a model's alias too when it differs — a
    lookup that misses is an edge silently dropped, and a lookup that guesses is an
    edge pointed at the wrong table.
    """
    index: Dict[str, Relation] = {}
    for node in man.models().values():
        relation = _relation_of(node)
        if not relation:
            continue
        index.setdefault(str(node.get("name")), relation)
        alias = node.get("alias")
        if alias:
            index.setdefault(str(alias), relation)
    for node in man.sources.values():
        relation = _relation_of(node)
        if not relation:
            continue
        source_name = node.get("source_name")
        name = node.get("name")
        if source_name and name:
            index.setdefault(f"{source_name}__{name}", relation)
        if name:
            index.setdefault(str(name), relation)
    for node in man.seeds().values():
        relation = _relation_of(node)
        if relation:
            index.setdefault(str(node.get("name")), relation)
    return index


# ---------------------------------------------------------------------------------------
# Classifications and tags — the facets, as OpenMetadata governance
# ---------------------------------------------------------------------------------------

# One classification per facet family rather than one flat bag, because
# `mutuallyExclusive` is a real constraint the server enforces: a column has exactly
# one role and exactly one additivity, and declaring that stops a later hand-edit from
# tagging a column both `Measure` and `Dimension`. `ColumnPII` is not exclusive — a
# quasi-identifier can also be an indirect one.
#
# Descriptions are this repository's own, not paraphrases of somebody else's: each
# states the consequence of the facet, because a tag whose description restates its
# name teaches a BI user nothing.
FACET_CLASSIFICATIONS: Dict[str, Dict[str, Any]] = {
    "role": {
        "classification": "ColumnRole",
        "description": (
            "What a conformed column is, structurally. Derived from "
            "`ontology/column-annotations.json`; a column with no recorded role "
            "carries no tag rather than a default."
        ),
        "mutuallyExclusive": True,
        "tags": {
            "identifier": (
                "Identifies a row or an entity. Arithmetic on it is always a bug, "
                "even where the warehouse type is numeric."
            ),
            "measure": "A quantity intended for aggregation. Check its additivity tag first.",
            "dimension": "A value to group or filter by.",
            "timestamp": "A point in time; the grain of any time-series cut over this table.",
            "flag": "A boolean or two-valued indicator.",
            "text": "Free text. Not a closed domain, not safe to group by.",
        },
    },
    "additivity": {
        "classification": "ColumnAdditivity",
        "description": (
            "Whether SUM() over this column is meaningful, and at which grain "
            "(analytics rule 11). Absent means undecided, never 'additive'."
        ),
        "mutuallyExclusive": True,
        "tags": {
            "additive": "Summable across every dimension including time.",
            "semi_additive": (
                "Summable across some dimensions but not time — a balance or a stock "
                "level. Summing it across periods double-counts."
            ),
            "non_additive": (
                "Never summable — a rate, a ratio, a price per unit. Store the "
                "numerator and denominator and define the ratio as a metric."
            ),
        },
    },
    "unit": {
        "classification": "ColumnUnit",
        "description": "The unit a conformed column's values are expressed in.",
        "mutuallyExclusive": True,
        "tags": {
            "currency": "A monetary amount. Mixing currencies without conversion is a defect.",
            "count": "A cardinality.",
            "quantity": "A physical or logical quantity.",
            "percent": "A proportion. Non-additive by construction.",
            "duration": "An elapsed time.",
            "date": "A calendar value.",
            "none": "Dimensionless.",
        },
    },
    "pii": {
        "classification": "ColumnPII",
        "description": (
            "Personal-data class beyond OpenMetadata's system `PII` classification. "
            "`pii: direct` is tagged `PII.Sensitive` instead; these cover the classes "
            "the system classification has no member for."
        ),
        "mutuallyExclusive": False,
        "tags": {
            "quasi": (
                "Quasi-identifier: not identifying alone, identifying in combination. "
                "Masking it is usually the wrong remedy — generalisation or "
                "suppression at the grain is."
            ),
            "indirect": (
                "Indirectly identifying through a join to another table. The "
                "disclosure risk lives in the join, not in this column."
            ),
        },
    },
}

# The system classification. `PII.Sensitive` and `PII.NonSensitive` are OpenMetadata's
# own members; there is no third one, so `pii: none` is expressed by the absence of a
# PII tag rather than by an invented `PII.None`.
SYSTEM_PII_TAG = "PII.Sensitive"

PROVENANCE_CLASSIFICATION = {
    "classification": "DataProvenance",
    "description": (
        "How a column or table came to exist, as distinct from what it means. Applied "
        "by scripts/openmetadata_sync.py from the repository's own artifacts."
    ),
    "mutuallyExclusive": False,
    "tags": {
        "DltSystemColumn": (
            "Inserted by a dlt load, not by the source system. Carries load "
            "provenance, never business meaning: never a measure, never a dimension "
            "to group a business question by."
        ),
        "DltSystemTable": (
            "A dlt bookkeeping table (`_dlt_loads`, `_dlt_version`, "
            "`_dlt_pipeline_state`). Load history, not business data."
        ),
        "ConformedColumn": (
            "Carries a conformed column contract: the same name means the same thing "
            "in every connector that supplies this concept."
        ),
        "AdapterModel": (
            "Realises one conformed concept for one connector. Its column list is "
            "governed by that concept's contract in `ontology/column-memory.json`."
        ),
    },
}


def tag_name(value: str) -> str:
    """`semi_additive` -> `SemiAdditive`. Tag names are entity names, not snake_case."""
    return "".join(part.capitalize() for part in str(value).split("_"))


def build_classifications() -> Dict[str, Any]:
    """CreateClassification + CreateTag payloads. Deterministic and use-case free."""
    classifications: List[Dict[str, Any]] = []
    tags: List[Dict[str, Any]] = []
    for spec in list(FACET_CLASSIFICATIONS.values()) + [PROVENANCE_CLASSIFICATION]:
        classifications.append({
            "name": spec["classification"],
            "displayName": spec["classification"],
            "description": spec["description"],
            "mutuallyExclusive": spec["mutuallyExclusive"],
            "provider": "user",
        })
        for value, description in spec["tags"].items():
            tags.append({
                "classification": spec["classification"],
                "name": tag_name(value),
                "displayName": tag_name(value),
                "description": description,
                "provider": "user",
            })
    return {
        "generated_by": "scripts/openmetadata_sync.py",
        "system_tags_used": [SYSTEM_PII_TAG],
        "classifications": classifications,
        "tags": tags,
    }


def tag_label(tag_fqn: str, description: str = "") -> Dict[str, Any]:
    """A `tagLabel`. `labelType: Automated` because a generator applied it.

    Not `Manual` — that is the value a person clicking in the UI produces, and the
    difference is what lets a reviewer tell a governance decision from a projection.
    `state: Confirmed` because the annotation it came from is a recorded decision, not
    a suggestion for someone to approve.
    """
    label = {
        "tagFQN": tag_fqn,
        "source": "Classification",
        "labelType": "Automated",
        "state": "Confirmed",
    }
    if description:
        label["description"] = description
    return label


# ---------------------------------------------------------------------------------------
# Glossary
# ---------------------------------------------------------------------------------------


def _concept_description(entry: Dict[str, Any], contract: Optional[Dict[str, Any]]) -> str:
    """A description built from facts the repository holds, never a business definition.

    OpenMetadata requires `description` on a glossary term, and nothing in this
    repository records what a concept *means* in prose — that is a human deliverable
    (rule 5). What it does hold is the concept's core class, which connectors supply
    it, which dbt models realise it, and how wide its column contract is. Stating
    those is honest; writing "Represents a customer in the business" is the invented
    definition an ontology is famous for.
    """
    lines = [
        f"Conformed concept **{entry['concept']}** "
        f"(`{entry.get('core_class') or 'unclassified'}`)."
    ]
    implemented = entry.get("implemented_by") or []
    planned = entry.get("planned_by") or []
    if implemented:
        lines.append(f"Supplied by {len(implemented)} connector(s): {', '.join(implemented)}.")
    else:
        lines.append("No connector supplies it yet.")
    if planned:
        lines.append(f"Planned by: {', '.join(planned)}.")
    if contract:
        lines.append(
            f"Column contract: {contract.get('column_count', 0)} conformed column(s); "
            f"adapters {', '.join(sorted(contract.get('adapters', {}).values()))}."
        )
        partial = contract.get("partial_for") or []
        if partial:
            lines.append(
                f"Partial for {', '.join(partial)} — those adapters build their column "
                "list through a macro, so the contract cannot name every column they carry."
            )
    lines.append(
        "Derived from `ontology/index.json`; no business definition is asserted here "
        "because none is recorded in the repository."
    )
    return "\n\n".join(lines)


def _column_description(entry: Dict[str, Any]) -> str:
    """A conformed column's term body — its own recorded definition plus its facets."""
    lines = []
    definition = (entry.get("definition") or "").strip()
    if definition:
        lines.append(definition)
    else:
        lines.append(
            f"Conformed column **{entry['column']}**. No definition is recorded; its "
            "facets below are what the repository knows."
        )
    facts = []
    if entry.get("role"):
        facts.append(f"role `{entry['role']}`")
    if entry.get("additivity"):
        facts.append(f"additivity `{entry['additivity']}`")
    if entry.get("unit"):
        facts.append(f"unit `{entry['unit']}`")
    if entry.get("pii") and entry["pii"] != "none":
        facts.append(f"PII `{entry['pii']}`")
    if facts:
        lines.append("Facets: " + ", ".join(facts) + ".")
    if entry.get("additivity") in ("semi_additive", "non_additive"):
        lines.append(
            "**Do not SUM() this column** without reading its additivity: summing it "
            "produces a plausible number that is wrong."
        )
    if entry.get("domain"):
        lines.append("Closed domain: " + ", ".join(str(v) for v in entry["domain"]) + ".")
    concepts = entry.get("concepts") or []
    if concepts:
        lines.append(f"Carried by concept(s): {', '.join(concepts)}.")
    connectors = entry.get("connectors") or []
    if connectors:
        lines.append(f"Supplied by connector(s): {', '.join(connectors)}.")
    return "\n\n".join(lines)


def build_glossary(
    index: Optional[Dict[str, Any]],
    column_memory: Optional[Dict[str, Any]],
    annotations: Optional[Dict[str, Any]],
    cfg: Config,
    slug: str,
) -> Dict[str, Any]:
    """One glossary; concept terms and conformed-column terms, both flat.

    Columns are **not** children of concepts. A conformed column belongs to several
    concepts at once — `Account` is carried by `fact_budgets`, `fact_vouchers`, and
    `fact_supplier_invoice_rows` — and `parent` is single-valued, so nesting would
    force a choice the data does not support. `relatedTerms` carries the real, n-ary
    relationship instead.
    """
    terms: List[Dict[str, Any]] = []
    concepts = (index or {}).get("concepts") or []
    contracts = {c["concept"]: c for c in ((column_memory or {}).get("contracts") or [])}

    for entry in concepts:
        name = entry["concept"]
        term: Dict[str, Any] = {
            "glossary": cfg.glossary,
            "name": name,
            "displayName": name,
            "description": _concept_description(entry, contracts.get(name)),
        }
        if entry.get("id"):
            # `iri` is CreateGlossaryTerm's own field for a term's canonical identifier
            # in its source ontology — exactly what ontology/ontology.yml pins.
            term["iri"] = entry["id"]
        terms.append(term)

    concept_names = {c["concept"] for c in concepts}
    for entry in ((annotations or {}).get("columns") or []):
        name = entry["column"]
        related = sorted(set(entry.get("concepts") or []) & concept_names)
        term = {
            "glossary": cfg.glossary,
            "name": name,
            "displayName": name,
            "description": _column_description(entry),
        }
        if related:
            term["relatedTerms"] = [fqn(cfg.glossary, c) for c in related]
        tags = [tag_label(t) for t in _facet_tags(entry)]
        if tags:
            term["tags"] = tags
        terms.append(term)

    return {
        "generated_by": "scripts/openmetadata_sync.py",
        "glossary": {
            "name": cfg.glossary,
            "displayName": cfg.glossary_display_name,
            "description": (
                f"Business glossary for the `{slug}` use-case, projected from its "
                "ontology. Concept terms come from `ontology/index.json`; conformed "
                "column terms from `ontology/column-annotations.json`. Git is the "
                "source of truth — edit the artifacts and regenerate, never the "
                "catalog."
            ),
            "mutuallyExclusive": False,
            "provider": "user",
        },
        "terms": terms,
        "unannotated_columns": sorted((annotations or {}).get("unannotated") or []),
    }


def _facet_tags(entry: Dict[str, Any]) -> List[str]:
    """Every tag FQN an annotated column earns. Absent facets earn nothing."""
    out: List[str] = []
    for facet, spec in FACET_CLASSIFICATIONS.items():
        value = entry.get(facet)
        if not value:
            continue
        if facet == "pii":
            if value == "direct":
                out.append(SYSTEM_PII_TAG)
                continue
            if value == "none":
                continue
        if str(value) not in spec["tags"]:
            continue
        out.append(f"{spec['classification']}.{tag_name(str(value))}")
    return out


# ---------------------------------------------------------------------------------------
# Tag applications — which tag lands on which column, in which physical table
# ---------------------------------------------------------------------------------------


def build_tag_applications(
    annotations: Optional[Dict[str, Any]],
    column_memory: Optional[Dict[str, Any]],
    relations: Dict[str, Relation],
    cfg: Config,
) -> Dict[str, Any]:
    """One record per (column FQN, tag). The catalog needs physical targets.

    An annotation is recorded once per *conformed* column and applies to every adapter
    model that declares it — 272 decisions covering 952 (column, connector) pairs. The
    catalog has no conformed layer, so the projection has to fan out to every physical
    column, and every one of those columns has to exist in a resolvable relation.
    """
    annotated = {e["column"]: e for e in ((annotations or {}).get("columns") or [])}
    applications: List[Dict[str, Any]] = []
    seen: set = set()
    unresolved: List[str] = []
    model_tags: List[Dict[str, Any]] = []

    for contract in ((column_memory or {}).get("contracts") or []):
        for connector, model in sorted((contract.get("adapters") or {}).items()):
            relation = relations.get(model)
            if relation is None:
                unresolved.append(f"{model}: adapter model resolves to no manifest node")
                continue
            model_tags.append({
                "entity": "table",
                "fqn": relation.table_fqn(cfg),
                "dbt_node": model,
                "concept": contract["concept"],
                "connector": connector,
                "tags": ["DataProvenance.AdapterModel"],
            })
            for column in contract.get("conformed") or []:
                entry = annotated.get(column)
                if not entry:
                    continue
                tags = _facet_tags(entry)
                if not tags:
                    continue
                column_fqn = relation.column_fqn(cfg, column)
                if column_fqn in seen:
                    continue
                seen.add(column_fqn)
                applications.append({
                    "entity": "column",
                    "fqn": column_fqn,
                    # Carried separately, not re-split out of `fqn`: a component may be
                    # quoted and contain a dot, so splitting on the last dot is wrong
                    # exactly where it matters.
                    "table_fqn": relation.table_fqn(cfg),
                    "column": column,
                    "concept": contract["concept"],
                    "connector": connector,
                    "tags": tags + ["DataProvenance.ConformedColumn"],
                })

    return {
        "generated_by": "scripts/openmetadata_sync.py",
        "note": (
            "A work list, not a payload: `tags` are tag FQNs, and the `tagLabel` around "
            "each is a constant of this bridge (Automated/Confirmed/Classification) "
            "built at push time. Embedding the full label per row repeated four "
            "constant fields 1300 times and taught a reader nothing. Applied with "
            "PATCH against the entity, never PUT: a PUT of a Table would replace the "
            "columns the dbt connector owns."
        ),
        "columns": applications,
        "tables": model_tags,
        "unresolved": sorted(set(unresolved)),
    }


# ---------------------------------------------------------------------------------------
# Deep column lineage — the reason this bridge exists
# ---------------------------------------------------------------------------------------


def build_column_lineage(
    column_memory: Optional[Dict[str, Any]],
    relations: Dict[str, Relation],
    cfg: Config,
) -> Dict[str, Any]:
    """`AddLineageRequest` per (upstream table, downstream table) pair.

    The standard dbt connector gives table-to-table lineage from `parent_map` and stops
    there. `ontology/column-memory.json` holds 1024 bindings that each resolve a
    conformed column through the whole chain — `select *` passthroughs, renames, union
    branches — back to the raw source column, with the transform class and the hop
    count. That is what makes this projection worth the code: a BI user clicking
    `TotalToPay` sees the raw API field it came from, not the staging model next door.

    Two shapes matter and both are the spec's, not ours:

    - The request is per **table pair**, with `columnsLineage` inside. So bindings are
      grouped by (source relation, target relation) before anything is emitted.
    - `fromColumns` is a **list** per `toColumn`. A conformed column fed by several
      upstream columns — a union across branches, a derived expression — is one
      `ColumnLineage` with several sources, not several conflicting edges.
    """
    bindings = (column_memory or {}).get("bindings") or []
    contracts = {c["concept"]: c for c in ((column_memory or {}).get("contracts") or [])}

    # (source_relation_key, target_relation_key) -> {to_column: {from_columns}, ...}
    pairs: Dict[Tuple[str, str], Dict[str, Any]] = {}
    unresolved_sources: Dict[str, int] = {}
    unresolved_targets: Dict[str, int] = {}
    transforms: Dict[str, int] = {}

    for binding in bindings:
        contract = contracts.get(binding["concept"])
        target_model = (contract or {}).get("adapters", {}).get(binding["connector"])
        if not target_model:
            unresolved_targets[f"{binding['concept']}/{binding['connector']}"] = (
                unresolved_targets.get(f"{binding['concept']}/{binding['connector']}", 0) + 1
            )
            continue
        target = relations.get(target_model)
        source = relations.get(binding["source_model"])
        if source is None:
            # A parse artifact, not a table: `NULL`, an unnest alias, a struct field.
            # Emitting it would mint a catalog entity for something that does not exist.
            unresolved_sources[binding["source_model"]] = (
                unresolved_sources.get(binding["source_model"], 0) + 1
            )
            continue
        if target is None:
            unresolved_targets[target_model] = unresolved_targets.get(target_model, 0) + 1
            continue
        if source.unique_id == target.unique_id:
            continue
        key = (source.table_fqn(cfg), target.table_fqn(cfg))
        entry = pairs.setdefault(key, {
            "from": source.table_fqn(cfg),
            "to": target.table_fqn(cfg),
            "from_type": "table",
            "to_type": "table",
            "columns": {},
            "transforms": set(),
            "max_hops": 0,
        })
        column_key = target.column_fqn(cfg, binding["column"])
        entry["columns"].setdefault(column_key, set()).add(
            source.column_fqn(cfg, binding["source_column"])
        )
        entry["transforms"].add(binding.get("transform", "unknown"))
        entry["max_hops"] = max(entry["max_hops"], int(binding.get("hops") or 0))
        transforms[binding.get("transform", "unknown")] = (
            transforms.get(binding.get("transform", "unknown"), 0) + 1
        )

    edges: List[Dict[str, Any]] = []
    multi_source_columns = 0
    for (_from_fqn, _to_fqn), entry in sorted(pairs.items()):
        columns_lineage = []
        for to_column, from_columns in sorted(entry["columns"].items()):
            if len(from_columns) > 1:
                multi_source_columns += 1
            columns_lineage.append({
                "fromColumns": sorted(from_columns),
                "toColumn": to_column,
            })
        kinds = ", ".join(sorted(entry["transforms"]))
        edges.append({
            "edge": {
                "fromEntity": {"type": "table", "fullyQualifiedName": entry["from"]},
                "toEntity": {"type": "table", "fullyQualifiedName": entry["to"]},
                "lineageDetails": {
                    "source": LINEAGE_SOURCE,
                    "description": (
                        f"Column lineage resolved by scripts/dbt_column_lineage.py "
                        f"through {entry['max_hops']} dbt model hop(s); transform "
                        f"class(es): {kinds}. Source of truth: "
                        f"ontology/column-memory.json."
                    ),
                    "columnsLineage": columns_lineage,
                },
            }
        })

    return {
        "generated_by": "scripts/openmetadata_sync.py",
        "lineage_source": LINEAGE_SOURCE,
        "edges": edges,
        "stats": {
            "bindings": len(bindings),
            "table_pairs": len(edges),
            "column_edges": sum(len(e["edge"]["lineageDetails"]["columnsLineage"])
                                for e in edges),
            "multi_source_columns": multi_source_columns,
            "transforms": dict(sorted(transforms.items())),
        },
        "dropped": {
            "unresolved_source_models": dict(sorted(unresolved_sources.items())),
            "unresolved_target_models": dict(sorted(unresolved_targets.items())),
        },
    }


# ---------------------------------------------------------------------------------------
# dlt load columns — the provenance nobody declares
# ---------------------------------------------------------------------------------------

# dlt's normalizer adds these to the tables it loads. Definitions are dlt's own
# documented semantics (dlthub.com/docs/general-usage/destination-tables), stated here
# because the catalog needs them in prose and no artifact in this repository carries
# them. They are a closed, documented set — not a guess about a particular warehouse.
DLT_COLUMNS: Dict[str, str] = {
    "_dlt_id": (
        "Row key. Unique identifier dlt assigns to every row in every table it loads, "
        "root and nested. Load provenance, not a business key: joining on it across "
        "loads is meaningless and grouping by it is always wrong."
    ),
    "_dlt_load_id": (
        "Load package identifier. Names the pipeline run that inserted the row, and "
        "joins to `_dlt_loads` for its timestamp and status. The correct column for "
        "'what arrived when', and the correct one to exclude from a business grain."
    ),
    "_dlt_parent_id": (
        "Parent row key. Present only on nested tables; references the `_dlt_id` of "
        "the row in the parent table this one was unpacked from."
    ),
    "_dlt_list_idx": (
        "Position of this item in the source list it was unpacked from. Present only "
        "on nested tables built from a JSON array; it preserves order, and it is not "
        "a quantity."
    ),
    "_dlt_root_id": (
        "Root row key. Added to nested tables loaded with the `merge` write "
        "disposition so a nested row can be traced to its root-table row."
    ),
}

DLT_TABLES: Dict[str, str] = {
    "_dlt_loads": (
        "One row per completed load package: load id, schema name, status, insertion "
        "timestamp, schema version hash. The load history of the pipeline."
    ),
    "_dlt_version": (
        "Schema version history — every version dlt has inferred, with its hash and "
        "the full JSON schema it corresponds to."
    ),
    "_dlt_pipeline_state": (
        "Internal pipeline state that makes incremental loading work: cursors and "
        "checkpoints across runs. Never business data."
    ),
}


def _dlt_from_duckdb(
    path: Path, schema: Optional[str],
) -> Tuple[Dict[Tuple[str, str], List[str]], str]:
    """({(schema, table): dlt columns present}, evidence). duckdb absent means skip."""
    try:
        import duckdb  # noqa: PLC0415 - optional, the same shape as sqlglot elsewhere
    except ImportError:
        return {}, "duckdb not installed"
    if not path.exists():
        return {}, f"no warehouse at {path}"
    try:
        con = duckdb.connect(str(path), read_only=True)
    except Exception as exc:  # noqa: BLE001 - a locked or corrupt file must not abort
        return {}, f"could not open {path.name}: {type(exc).__name__}"
    try:
        query = (
            "select table_schema, table_name, column_name from information_schema.columns"
        )
        params: Sequence[Any] = ()
        if schema:
            query += " where table_schema = ?"
            params = (schema,)
        rows = con.execute(query, params).fetchall()
    finally:
        con.close()
    found: Dict[Tuple[str, str], List[str]] = {}
    for table_schema, table_name, column_name in rows:
        key = (str(table_schema), str(table_name))
        if table_name in DLT_TABLES:
            found.setdefault(key, [])
        elif column_name in DLT_COLUMNS:
            found.setdefault(key, []).append(str(column_name))
    return {k: sorted(v) for k, v in found.items()}, f"duckdb: {path.name}"


def _dlt_from_manifest(
    man: Optional[Manifest], cfg: Config,
) -> Dict[str, Tuple[str, List[str]]]:
    """dlt columns a dbt project declares — in `sources.yml` `columns:` or on a model.

    Free, and it works where `duckdb` is absent: the source column contracts this
    repository bootstraps (`--emit-source-columns`) declare the raw table's real column
    list, so a dlt-loaded source that declares `_dlt_load_id` is found here without
    ever opening a warehouse.
    """
    if man is None:
        return {}
    found: Dict[str, Tuple[str, List[str]]] = {}
    nodes: Iterable[Dict[str, Any]] = list(man.sources.values()) + list(man.models().values())
    for node in nodes:
        relation = _relation_of(node)
        if not relation:
            continue
        declared = sorted(c for c in (node.get("columns") or {}) if c in DLT_COLUMNS)
        is_system = relation.table in DLT_TABLES
        if not declared and not is_system:
            continue
        key = relation.table_fqn(cfg)
        existing = found.get(key, (relation.table, []))
        found[key] = (relation.table, sorted(set(existing[1]) | set(declared)))
    return found


def build_dlt_provenance(
    use_case: Path, man: Optional[Manifest], cfg: Config, with_warehouse: bool = False,
) -> Dict[str, Any]:
    """Descriptions, tags, and glossary terms for the columns a dlt load inserts.

    These columns are the one part of a dlt-loaded warehouse that no source system
    declares and no analyst recognises. Left untagged they read as ordinary columns:
    `_dlt_list_idx` is an integer that looks summable, and `_dlt_id` is a string that
    looks like a business key. Tagging them as provenance is what keeps them out of a
    grain and out of a metric.

    The *definitions* — five columns, three system tables, their meanings and their
    glossary terms — are a closed documented set and are always emitted. The
    *applications* need evidence, and there are two sources:

    - **What the dbt project declares.** Free, committed, and deterministic: a source
      contract that lists `_dlt_load_id` is found without opening anything.
    - **A dlt-loaded DuckDB warehouse**, behind `--with-warehouse`. Off by default,
      and that is a correctness decision rather than a performance one: a warehouse is
      gitignored and rebuilt by `dlt_agent_costs.py --run`, so a committed bundle that
      read one would differ between a machine that has built it and a fresh clone —
      and `--check` would be permanently red. Same rule that keeps cache counters out
      of `column-memory.json`'s provenance block.

    The payload states which evidence it used, because a bundle reporting zero dlt
    columns because nothing was read must not read the same as one reporting zero
    because the warehouse has none.
    """
    # {table FQN: (bare table name, dlt columns present)}. The bare name is carried
    # alongside the FQN rather than re-split out of it, because an FQN component may
    # itself be quoted and contain a dot.
    tables: Dict[str, Tuple[str, List[str]]] = {}
    evidence: List[str] = []

    from_manifest = _dlt_from_manifest(man, cfg)
    if from_manifest:
        evidence.append("dbt-declared columns")
    for table_fqn, (name, columns) in from_manifest.items():
        tables[table_fqn] = (name, sorted(set(columns)))

    if cfg.dlt_warehouse and not with_warehouse:
        evidence.append(
            f"warehouse {cfg.dlt_warehouse} declared but not read "
            "(--with-warehouse; it is gitignored, so reading it here would make this "
            "bundle differ between clones)"
        )
    elif cfg.dlt_warehouse:
        warehouse = (use_case / cfg.dlt_warehouse).resolve()
        from_warehouse, note = _dlt_from_duckdb(warehouse, cfg.dlt_schema)
        evidence.append(note)
        # A DuckDB file *is* the database; its stem is the catalog name unless the
        # config overrides it. Composing the FQN here keeps the reader a pure schema
        # query with no opinion about naming.
        database = cfg.database_override or warehouse.stem
        for (schema, table), columns in from_warehouse.items():
            table_fqn = fqn(cfg.service, database, cfg.schema_override or schema, table)
            existing = tables.get(table_fqn, (table, []))
            tables[table_fqn] = (table, sorted(set(existing[1]) | set(columns)))

    applications: List[Dict[str, Any]] = []
    for table_fqn, (name, columns) in sorted(tables.items()):
        if name in DLT_TABLES:
            applications.append({
                "entity": "table",
                "fqn": table_fqn,
                "description": DLT_TABLES[name],
                "tags": ["DataProvenance.DltSystemTable"],
            })
        for column in columns:
            applications.append({
                "entity": "column",
                "fqn": f"{table_fqn}.{fqn_part(column)}",
                "table_fqn": table_fqn,
                "column": column,
                "description": DLT_COLUMNS[column],
                # `_dlt_list_idx` is an integer and every other one is a key, so
                # `identifier` is right for all five: none of them is a quantity, and
                # the role tag is what stops a BI tool offering SUM() on the one that
                # looks like a number.
                "tags": ["DataProvenance.DltSystemColumn", "ColumnRole.Identifier"],
            })

    glossary_terms = [
        {
            "name": column.lstrip("_"),
            "displayName": column,
            "description": description,
            "synonyms": [column],
        }
        for column, description in sorted(DLT_COLUMNS.items())
    ]

    return {
        "generated_by": "scripts/openmetadata_sync.py",
        "evidence": evidence or ["none — no dlt warehouse declared and no dbt-declared "
                                 "dlt columns"],
        "known_columns": sorted(DLT_COLUMNS),
        "known_tables": sorted(DLT_TABLES),
        "applications": applications,
        "glossary_terms": glossary_terms,
        "stats": {
            "tables_tagged": sum(1 for a in applications if a["entity"] == "table"),
            "tables_carrying_dlt_columns": len(
                {a["table_fqn"] for a in applications if a["entity"] == "column"}
            ),
            "column_applications": sum(
                1 for a in applications if a["entity"] == "column"
            ),
            "glossary_terms": len(DLT_COLUMNS),
        },
    }


# ---------------------------------------------------------------------------------------
# The mechanical layer — handed back to upstream's connector
# ---------------------------------------------------------------------------------------


def build_ingestion_config(
    use_case: Path, slug: str, manifest: Optional[Path], cfg: Config,
) -> str:
    """The dbt workflow config `metadata ingest -c` consumes.

    Written as text rather than dumped from a dict for the same reason the source-column
    emitter inserts text: this file carries `$OPENMETADATA_SERVER_URL`-style references
    a YAML round-trip would quote, and comments that explain why each switch is set the
    way it is. Its field names are the spec's
    (openmetadata-spec/.../metadataIngestion/dbtPipeline.json).
    """
    target = (manifest.parent if manifest else use_case / "dbt_project/target")
    rel = os.path.relpath(target, REPO)
    return f"""\
# Generated by scripts/openmetadata_sync.py — do not hand-edit.
# Regenerate: python3 scripts/use_case_sync.py --use-case {slug} --stage openmetadata
#
# The MECHANICAL layer of the OpenMetadata projection: tables, descriptions, owners,
# dbt tests, and model-level lineage, all built by upstream's own dbt connector. This
# bridge does not re-derive any of it — see the module docstring of
# scripts/openmetadata_sync.py for why.
#
#   {INGESTION_INSTALL}
#   metadata ingest -c {BUNDLE_DIR}/ingestion/dbt.yaml
#
# The enrichment layer — deep column lineage, glossary, facet tags, dlt provenance —
# is in ../bundle/ and is pushed by:
#
#   python3 scripts/openmetadata_sync.py --use-case {slug} --push
#
# `serviceName` is the OpenMetadata database service this use-case's warehouse is
# registered under. It is declared in {CONFIG_NAME}; nothing in manifest.json knows it.

source:
  type: dbt
  serviceName: {cfg.service}
  sourceConfig:
    config:
      type: DBT
      dbtConfigSource:
        dbtConfigType: local
        dbtManifestFilePath: {rel}/manifest.json
        dbtCatalogFilePath: {rel}/catalog.json
        dbtRunResultsFilePath: {rel}/run_results.json
      # False on purpose. dbt descriptions are already the source of truth for the
      # models this repository generates, but a catalog user may have curated a
      # description the repository has no record of; overwriting it on every ingest is
      # how a unidirectional pipeline turns into data loss.
      dbtUpdateDescriptions: false
      dbtUpdateOwners: false
      includeTags: true
      dbtClassificationName: dbtTags
      searchAcrossDatabases: false

sink:
  type: metadata-rest
  config: {{}}

workflowConfig:
  openMetadataServerConfig:
    hostPort: ${{{SERVER_URL_ENV}}}
    authProvider: openmetadata
    securityConfig:
      jwtToken: ${{{AUTH_TOKEN_ENV}}}
"""


# ---------------------------------------------------------------------------------------
# RDF alignment — our topology in OpenMetadata's own vocabulary
# ---------------------------------------------------------------------------------------

# open-metadata/OpenMetadataStandards publishes OWL ontologies, SHACL shapes and
# JSON-LD contexts under rdf/, pinned here as the external/OpenMetadataStandards
# submodule. This repository already emits Turtle for its own topology, so the
# alignment is a projection rather than a translation: the same concepts, re-stated
# with `om:` terms so a consumer that speaks OpenMetadata's vocabulary can read our
# graph without knowing ours.
#
# Both constants below were wrong before the submodule was pinned, which is the whole
# argument for pinning it. The namespace was guessed as `.../schema/` (it is
# `.../ontology/`), and the asset-to-term relation was invented as `om:glossaryTerm`
# (no such property exists; `om:GlossaryTerm rdfs:subClassOf skos:Concept` and
# `om:Table rdfs:subClassOf dcat:Dataset`, so the correct, already-standard relation
# is `dcat:theme`). `check_vocabulary` below now fails the emit if a term used here is
# absent from the pinned ontology, so the next guess cannot ship.
OM_NAMESPACE = "https://open-metadata.org/ontology/"
STANDARDS_SUBMODULE = REPO / "external/OpenMetadataStandards"
OM_ONTOLOGY = STANDARDS_SUBMODULE / "rdf/ontology/openmetadata.ttl"
OM_CONTEXT = STANDARDS_SUBMODULE / "rdf/contexts/dataAsset.jsonld"
OM_SHAPES = STANDARDS_SUBMODULE / "rdf/shapes/openmetadata-shapes.ttl"

# Every `om:` term the alignment asserts. Verified against the pinned ontology by
# `check_vocabulary`, so this list cannot drift from upstream in silence.
OM_TERMS = (
    "Table", "Column", "GlossaryTerm",
    "fullyQualifiedName", "hasColumn", "fromColumn", "description",
)


def check_vocabulary() -> Dict[str, Any]:
    """Every `om:` term the alignment uses must exist in the pinned ontology.

    Without the submodule this is unverifiable and the emitter says so rather than
    claiming a clean check — a validator that passes because it read nothing is worse
    than no validator. With it, an invented term or a moved namespace fails the emit.
    """
    if not OM_ONTOLOGY.exists():
        return {
            "status": "skip",
            "detail": "external/OpenMetadataStandards not initialised — "
                      "git submodule update --init external/OpenMetadataStandards",
        }
    text = OM_ONTOLOGY.read_text(encoding="utf-8")
    declared = set(re.findall(r"^om:(\w+)\s+a\s+owl:", text, re.M))
    namespace_ok = f"@prefix om: <{OM_NAMESPACE}>" in text
    missing = sorted(t for t in OM_TERMS if t not in declared)
    problems = []
    if not namespace_ok:
        actual = re.search(r"@prefix om:\s*<([^>]+)>", text)
        problems.append(
            f"namespace is {actual.group(1) if actual else '?'}, not {OM_NAMESPACE}"
        )
    if missing:
        problems.append(f"terms absent from the pinned ontology: {', '.join(missing)}")
    return {
        "status": "fail" if problems else "ok",
        "declared_terms": len(declared),
        "checked": len(OM_TERMS),
        "problems": problems,
    }


def _ttl_string(value: str) -> str:
    """A Turtle string literal. Unescaped quotes and backslashes break the parse."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_rdf_alignment(
    index: Optional[Dict[str, Any]],
    column_memory: Optional[Dict[str, Any]],
    lineage: Dict[str, Any],
    relations: Dict[str, Relation],
    cfg: Config,
    slug: str,
) -> str:
    """Turtle aligning this use-case's topology to OpenMetadata's asset vocabulary.

    It **uses** upstream's terms rather than redeclaring them. The earlier version
    restated `om:Table a owl:Class` and friends in its own header, on the reasoning
    that a consumer meeting a term has nowhere to look it up. That was right while the
    vocabulary was a guess and wrong once it is pinned: redeclaring a term upstream
    already defines makes this file an authority on somebody else's ontology, and it
    is exactly how the two drift. The header cites the pinned file instead, and
    `check_vocabulary` fails the emit if a term used here is not in it.

    Three relations carry the alignment, all of them already standard:

    - `dcat:theme` from an adapter table to its concept's glossary term.
      `om:Table rdfs:subClassOf dcat:Dataset` and `om:GlossaryTerm rdfs:subClassOf
      skos:Concept`, so DCAT's own dataset-to-concept property fits with nothing
      invented. There is no `om:glossaryTerm`; an earlier draft made one up.
    - `om:hasColumn` from a table to each conformed column it carries.
    - `om:fromColumn` from a conformed column to each raw column it came from —
      upstream declares it `rdfs:subPropertyOf prov:used`, so the deep column lineage
      arrives in a SPARQL consumer as PROV provenance for free. This is the payoff of
      pinning the standards repo: the same lineage the JSON bundle pushes, in the
      vocabulary a knowledge-graph consumer already speaks.
    """
    prefixes = (index or {}).get("prefixes") or {}
    topo = prefixes.get("topo", f"https://w3id.org/{slug}/topology#")
    conn = prefixes.get("conn", f"https://w3id.org/{slug}/connector#")
    # Catalog entities are identified by their OpenMetadata FQN, which is not an IRI.
    # They get an IRI in this use-case's own namespace — a namespace this repository
    # owns — with the FQN attached as `om:fullyQualifiedName`, which is upstream's own
    # identifier property. Minting them under `open-metadata.org` would be asserting an
    # IRI scheme upstream does not define.
    asset = f"{topo.rstrip('#')}/asset/"

    lines = [
        "# Generated by scripts/openmetadata_sync.py — do not hand-edit.",
        f"# Regenerate: python3 scripts/use_case_sync.py --use-case {slug} "
        "--stage openmetadata",
        "#",
        "# Aligns this use-case's conformed topology and column lineage to the",
        "# OpenMetadata vocabulary published by open-metadata/OpenMetadataStandards,",
        "# pinned as the external/OpenMetadataStandards submodule:",
        "#   ontology: rdf/ontology/openmetadata.ttl",
        "#   context:  rdf/contexts/dataAsset.jsonld",
        "#   shapes:   rdf/shapes/openmetadata-shapes.ttl",
        "#",
        "# Terms are used, never redeclared — upstream owns them.",
        "",
        f"@prefix om:   <{OM_NAMESPACE}> .",
        f"@prefix topo: <{topo}> .",
        f"@prefix conn: <{conn}> .",
        f"@prefix asset: <{asset}> .",
        "@prefix dcat: <http://www.w3.org/ns/dcat#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        "",
    ]

    contracts = {c["concept"]: c for c in ((column_memory or {}).get("contracts") or [])}
    # Column FQN -> the IRI minted for it, so lineage and `om:hasColumn` agree.
    #
    # `asset:`-prefixed names, not full IRIs: measured, full IRIs spent 63% of a
    # 727 KB file re-stating the same 55-character namespace ~3500 times — the same
    # "declare it once" argument that makes TOON worth using on a uniform record set.
    #
    # The local part is percent-encoded with dots, colons, and hyphens left alone,
    # which is what Turtle's PN_LOCAL grammar admits. That is not cosmetic: an FQN
    # component containing a dot is quoted by OpenMetadata, and encoding the quotes
    # (`%22`) is what keeps `svc.db.sch."my.table".col` from collapsing onto
    # `svc.db.sch.my.table.col`. A bare `.replace('"', '')` would silently merge them.
    column_iri: Dict[str, str] = {}

    def iri_for(fqn_value: str) -> str:
        if fqn_value not in column_iri:
            local = urllib.parse.quote(fqn_value, safe=".-_~:")
            column_iri[fqn_value] = f"asset:{local}"
        return column_iri[fqn_value]

    tables = 0
    for entry in sorted((index or {}).get("concepts") or [], key=lambda e: e["concept"]):
        concept = entry["concept"]
        contract = contracts.get(concept)
        if not contract:
            continue
        lines.append(f"<{entry['id']}> a om:GlossaryTerm ;")
        lines.append(f"    om:fullyQualifiedName {_ttl_string(fqn(cfg.glossary, concept))} ;")
        lines.append(f"    skos:prefLabel {_ttl_string(concept)} .")
        lines.append("")
        for connector, model in sorted((contract.get("adapters") or {}).items()):
            relation = relations.get(model)
            if relation is None:
                continue
            columns = [
                iri_for(relation.column_fqn(cfg, c))
                for c in contract.get("conformed") or []
            ]
            lines.append(f"conn:{model} a om:Table ;")
            lines.append(
                f"    om:fullyQualifiedName {_ttl_string(relation.table_fqn(cfg))} ;"
            )
            lines.append(f"    dcat:theme <{entry['id']}> ;")
            lines.append(
                f"    om:description "
                f"{_ttl_string(f'Adapter for {concept} from {connector}.')} ;"
            )
            if columns:
                lines.append("    om:hasColumn " + ",\n        ".join(columns) + " ;")
            lines.append(f"    rdfs:label {_ttl_string(model)} .")
            lines.append("")
            tables += 1

    # Column lineage, from the same edges the JSON bundle pushes. Only the
    # `om:fromColumn` arcs here; the type and the FQN are stated once per column
    # below, so a column appearing as both a source and a target is not restated.
    upstream_of: Dict[str, List[str]] = {}
    for edge in lineage.get("edges", []):
        for pair in edge["edge"]["lineageDetails"]["columnsLineage"]:
            target = iri_for(pair["toColumn"])
            for source in pair["fromColumns"]:
                upstream_of.setdefault(target, []).append(iri_for(source))

    # Every referenced column is typed exactly once, including the raw source columns
    # that only ever appear on the right of an `om:fromColumn`. An untyped IRI is a
    # dangling node in a knowledge graph, and SHACL will say so.
    for column_fqn, iri in sorted(column_iri.items()):
        sources = sorted(set(upstream_of.get(iri, [])))
        lines.append(f"{iri} a om:Column ;")
        terminator = " ;" if sources else " ."
        lines.append(f"    om:fullyQualifiedName {_ttl_string(column_fqn)}{terminator}")
        if sources:
            lines.append("    om:fromColumn " + ",\n        ".join(sources) + " .")
        lines.append("")
    column_edges = sum(len(v) for v in upstream_of.values())

    if tables == 0 and column_edges == 0:
        lines.append(
            "# No concept has both a column contract and a resolvable adapter model,"
        )
        lines.append("# and no column lineage resolved, so no alignment is asserted.")
        lines.append("# This is a statement about the use-case, not a gap in the emitter.")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------
# Knowledge — what an agent reads before it asks the catalog anything
# ---------------------------------------------------------------------------------------


def build_catalog_markdown(slug: str, cfg: Config, payload: Dict[str, Any]) -> str:
    lineage = payload["lineage"]["stats"]
    dropped = payload["lineage"]["dropped"]["unresolved_source_models"]
    glossary = payload["glossary"]
    dlt = payload["dlt"]
    unannotated = len(glossary.get("unannotated_columns") or [])
    concepts = sum(1 for t in glossary["terms"] if "iri" in t)
    columns = len(glossary["terms"]) - concepts
    return (
        _header(slug)
        + f"""
# OpenMetadata catalog — {slug}

The catalog is a **destination**. Every fact in it originates in this repository, is
regenerated by `use_case_sync.py --stage openmetadata`, and is pushed one way. A
description edited in the OpenMetadata UI is not read back here and will be
overwritten on the next push of the field that carries it; change the artifact.

## What is in it, and what is not

| | Count | Source |
| --- | --- | --- |
| Concept glossary terms | {concepts} | `ontology/index.json` |
| Conformed column terms | {columns} | `ontology/column-annotations.json` |
| Conformed columns with **no** annotation | {unannotated} | — |
| Column lineage edges | {lineage['column_edges']} across {lineage['table_pairs']} table pair(s) | `ontology/column-memory.json` |
| Columns with several upstream sources | {lineage['multi_source_columns']} | union branches and derived expressions |
| Tables carrying dlt load columns | {dlt['stats']['tables_carrying_dlt_columns']} | {', '.join(dlt['evidence'])} |
| dlt system tables tagged | {dlt['stats']['tables_tagged']} | same |

{_coverage_paragraph(unannotated, columns)}

Tables, table descriptions, dbt tests, and model-level lineage do **not** come from
this bundle. They come from upstream's dbt connector, configured in
`{BUNDLE_DIR}/ingestion/dbt.yaml`. If a table is missing from the catalog, the
connector has not run; pushing this bundle will not create it.

## The service name

Every FQN in this bundle starts with `{cfg.service}` — the OpenMetadata database
service the warehouse is registered under, declared in `{CONFIG_NAME}`. It is not
derived from anything in the dbt project, because nothing in the dbt project knows it.
If FQNs do not resolve on the server, that value is the first thing to check.

## Lineage the standard connector cannot give you

The dbt connector builds lineage from `parent_map`: table to table. The edges in
`bundle/column-lineage.json` are column to column, resolved through every hop back to
the raw source column, with the transform class recorded on the edge. Transform
classes present here: {', '.join(f"`{k}` ({v})" for k, v in lineage['transforms'].items()) or 'none'}.

{_dropped_paragraph(dropped)}

## Asking the catalog

`knowledge/mcp.md` in this directory has the agent surface. Search, entity lookup, and
lineage traversal are all read paths; nothing an agent does through them writes back
into this repository.
"""
    )


def _coverage_paragraph(unannotated: int, annotated: int) -> str:
    """State the coverage, and say which kind of zero a zero is.

    "0 conformed columns carry no facet tag" reads as complete coverage when the truth
    may be that there are no conformed columns at all — the same defect as a knowledge
    file that lists 89 columns and stays silent about the other 183.
    """
    if unannotated:
        return (
            f"**{unannotated} conformed column(s) carry no facet tag.** That is not an "
            "oversight in the push — it is the state of `column-annotations.json`, and "
            "it means those columns have had no additivity and no PII class decided. "
            "**Do not read the absence of a tag as `Additive` or as `not PII`.**"
        )
    if annotated:
        return (
            f"All {annotated} annotated conformed column(s) carry their facet tags; "
            "`column-annotations.json` lists none as unannotated."
        )
    return (
        "**This use-case has no column annotations at all**, so no column in the "
        "catalog carries a role, an additivity, or a PII tag from this bundle. That is "
        "the state of `ontology/column-annotations.json`, not a push that failed — run "
        "`column_annotations.py --propose --evidenced-only` to start one."
    )


def _dropped_paragraph(dropped: Dict[str, int]) -> str:
    if not dropped:
        return (
            "Every binding endpoint resolved to a dbt node, so no edge was dropped."
        )
    names = ", ".join(f"`{k}`" for k in sorted(dropped)[:8])
    total = sum(dropped.values())
    return (
        f"**{len(dropped)} binding endpoint(s) ({total} binding(s)) resolved to no dbt "
        f"node and were dropped**: {names}. These are SQL parse artifacts — an unnest "
        "alias, a struct field, a literal — not tables. Emitting them would create "
        "catalog entities for things that do not exist."
    )


def build_mcp_markdown(slug: str, cfg: Config) -> str:
    return (
        _header(slug)
        + f"""
# Asking OpenMetadata — the agent surface

Two ways in, both read-only from this repository's point of view, both credentialed
from the environment. **No token is ever written to disk by anything in this repo.**

## 1. The server's own MCP endpoint

A running OpenMetadata server exposes MCP. Register it with the environment variables,
never with literal values:

```json
{{
  "mcpServers": {{
    "openmetadata-{slug}": {{
      "url": "${{{SERVER_URL_ENV}}}/mcp",
      "headers": {{ "Authorization": "Bearer ${{{AUTH_TOKEN_ENV}}}" }}
    }}
  }}
}}
```

## 2. The REST API

```bash
# search
curl -s -H "Authorization: Bearer ${AUTH_TOKEN_ENV}" \\
  "${SERVER_URL_ENV}/api/v1/search/query?q=orders&index=table_search_index&size=10"

# one table, with its columns and tags
curl -s -H "Authorization: Bearer ${AUTH_TOKEN_ENV}" \\
  "${SERVER_URL_ENV}/api/v1/tables/name/{cfg.service}.<db>.<schema>.<table>?fields=columns,tags"

# column lineage
curl -s -H "Authorization: Bearer ${AUTH_TOKEN_ENV}" \\
  "${SERVER_URL_ENV}/api/v1/lineage/table/name/<fqn>?upstreamDepth=3&downstreamDepth=1"

# a glossary term
curl -s -H "Authorization: Bearer ${AUTH_TOKEN_ENV}" \\
  "${SERVER_URL_ENV}/api/v1/glossaryTerms/name/{cfg.glossary}.<term>"
```

## Which store answers which question

The catalog is the discovery surface, not the authority. Before quoting it back to a
user, know what it can and cannot settle:

| Question | Ask |
| --- | --- |
| Does a table exist, what is it called, who owns it | OpenMetadata |
| What does this conformed column mean, can I sum it | `ontology/column-annotations.json` — the catalog carries a projection of it |
| Which raw column does this value come from | `ontology/column-memory.json`, or the catalog's column lineage, which is the same data |
| Why was this modelled this way | AgentMemory, then the use-case spec |

A disagreement between the catalog and an artifact is a stale push, and the artifact
wins. Re-run the stage.
"""
    )


# ---------------------------------------------------------------------------------------
# Optional validation against the server's own generated models
# ---------------------------------------------------------------------------------------


SPEC_ROOT = REPO / "external/OpenMetadata/openmetadata-spec/src/main/resources/json/schema"


def check_against_pinned_spec(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the emitted payloads against the JSON schemas in the pinned submodule.

    Every enum member and required field this bridge writes was read off upstream's
    documentation and then hardcoded. Hardcoded is fine; *unverified* is not — an
    invented enum member is rejected by the server on push, one entity at a time,
    after the egress has already started. This reads the same schemas the server
    generates its models from, at the pinned SHA, offline.

    It is not a general JSON-Schema validator, deliberately: `jsonschema` is a
    dependency, and the four things worth checking here are closed enums and required
    keys. A partial check that runs everywhere beats a total one that is skipped.
    """
    if not SPEC_ROOT.exists():
        return {
            "status": "skip",
            "detail": "external/OpenMetadata not initialised — "
                      "git submodule update --init external/OpenMetadata",
        }

    def load(rel: str) -> Dict[str, Any]:
        return json.loads((SPEC_ROOT / rel).read_text(encoding="utf-8"))

    problems: List[str] = []
    checked = 0

    lineage_spec = load("type/entityLineage.json")["definitions"]
    sources = lineage_spec["lineageDetails"]["properties"]["source"]["enum"]
    if LINEAGE_SOURCE not in sources:
        problems.append(
            f"lineageDetails.source={LINEAGE_SOURCE!r} is not in the pinned enum "
            f"({', '.join(sources)})"
        )
    column_keys = set(lineage_spec["columnLineage"]["properties"])
    for edge in bundle["lineage"]["edges"]:
        details = edge["edge"]["lineageDetails"]
        checked += 1
        for pair in details["columnsLineage"]:
            unknown = set(pair) - column_keys
            if unknown:
                problems.append(f"columnLineage has unknown key(s): {sorted(unknown)}")
                break

    tag_spec = load("type/tagLabel.json")
    required = set(tag_spec.get("required") or [])
    label_types = tag_spec["properties"]["labelType"]["enum"]
    states = tag_spec["properties"]["state"]["enum"]
    probe = tag_label("X.Y")
    checked += 1
    if not required <= set(probe):
        problems.append(f"tagLabel is missing required field(s): {sorted(required - set(probe))}")
    if probe["labelType"] not in label_types:
        problems.append(f"tagLabel.labelType={probe['labelType']!r} not in {label_types}")
    if probe["state"] not in states:
        problems.append(f"tagLabel.state={probe['state']!r} not in {states}")

    term_spec = load("api/data/createGlossaryTerm.json")
    term_required = set(term_spec.get("required") or [])
    for term in bundle["glossary"]["terms"]:
        checked += 1
        missing = term_required - set(term)
        if missing:
            problems.append(f"glossaryTerm {term.get('name')} missing {sorted(missing)}")
            break

    dbt_spec = load("metadataIngestion/dbtPipeline.json")
    dbt_type = dbt_spec.get("definitions", {}).get("dbtConfigType", {})
    checked += 1

    return {
        "status": "fail" if problems else "ok",
        "spec": "external/OpenMetadata (pinned)",
        "checked": checked,
        "problems": problems[:10],
        "dbt_pipeline_spec_present": bool(dbt_spec),
        "dbt_config_type_declared": bool(dbt_type),
    }


def validate_with_sdk(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Validate emitted payloads against `openmetadata-ingestion`'s pydantic models.

    This is the one job the SDK does here. It is not the client: its wheel must match
    the server version exactly, and a bridge that hard-depends on that pin breaks on
    every server upgrade — so the push is plain REST and the SDK is an optional
    checker, exactly like sqlglot and rdflib elsewhere in this repository.
    """
    try:
        from metadata.generated.schema.api.lineage.addLineage import (  # noqa: PLC0415
            AddLineageRequest,
        )
        from metadata.generated.schema.api.data.createGlossaryTerm import (  # noqa: PLC0415
            CreateGlossaryTermRequest,
        )
        from metadata.generated.schema.api.classification.createClassification import (  # noqa: PLC0415,E501
            CreateClassificationRequest,
        )
    except ImportError:
        return {"status": "skip", "detail": f"openmetadata-ingestion absent — {INGESTION_INSTALL}"}

    errors: List[str] = []
    checked = 0
    for edge in bundle["lineage"]["edges"]:
        checked += 1
        try:
            AddLineageRequest(**edge)
        except Exception as exc:  # noqa: BLE001 - the message is the finding
            errors.append(f"lineage: {type(exc).__name__}: {str(exc)[:200]}")
    for term in bundle["glossary"]["terms"]:
        checked += 1
        try:
            CreateGlossaryTermRequest(**term)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"glossaryTerm {term.get('name')}: {str(exc)[:200]}")
    for classification in bundle["classifications"]["classifications"]:
        checked += 1
        try:
            CreateClassificationRequest(**classification)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"classification {classification.get('name')}: {str(exc)[:200]}")

    return {
        "status": "fail" if errors else "ok",
        "checked": checked,
        "errors": errors[:10],
        "error_count": len(errors),
    }


# ---------------------------------------------------------------------------------------
# Push — the only network path, and it is never implicit
# ---------------------------------------------------------------------------------------


class Pusher:
    """Minimal REST client. `urllib` on purpose: no dependency to drift from the server.

    Every call is idempotent by construction — PUT for creatable entities (OpenMetadata
    PUT is create-or-update), PATCH for tags on entities another ingestion owns. There
    is no DELETE anywhere in this module: a bridge that can delete a catalog entity on
    a bad artifact read is a bridge one regression away from wiping a production
    catalog.
    """

    def __init__(self, base_url: str, token: str, timeout: int = 60) -> None:
        self.base = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(self, method: str, path: str, body: Any = None,
                 content_type: str = "application/json") -> Tuple[int, Any]:
        url = f"{self.base}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                return response.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            return exc.code, detail
        except urllib.error.URLError as exc:
            return 0, str(exc.reason)

    def get(self, path: str) -> Tuple[int, Any]:
        return self._request("GET", path)

    def put(self, path: str, body: Any) -> Tuple[int, Any]:
        return self._request("PUT", path, body)

    def patch(self, path: str, ops: List[Dict[str, Any]]) -> Tuple[int, Any]:
        """JSON Patch, the only shape that enriches an entity without owning it.

        `PUT /tables` would replace the entity, discarding the columns the dbt
        connector just wrote. A patch of `add` operations touches exactly the paths
        named and nothing else.
        """
        if not ops:
            return 200, None
        return self._request(
            "PATCH", path, ops, content_type="application/json-patch+json"
        )


def push_bundle(bundle: Dict[str, Any], base_url: str, token: str,
                dry_run: bool) -> Dict[str, Any]:
    """Push in dependency order: classifications, tags, glossary, terms, then lineage.

    Order is not cosmetic. A tag label referencing a classification that does not exist
    is rejected, and a lineage edge is rejected if either endpoint is absent — which is
    also why the endpoints are *not* created here: the dbt connector owns them, and a
    404 on an edge is the correct signal that it has not run.
    """
    column_tables = {
        a["table_fqn"]
        for a in bundle["tags"]["columns"] + bundle["dlt"]["applications"]
        if a["entity"] == "column"
    }
    planned: List[Tuple[str, str]] = (
        [("PUT", "/api/v1/classifications")] * len(bundle["classifications"]["classifications"])
        + [("PUT", "/api/v1/tags")] * len(bundle["classifications"]["tags"])
        + [("PUT", "/api/v1/glossaries")]
        + [("PUT", "/api/v1/glossaryTerms")] * len(bundle["glossary"]["terms"])
        + [("PUT", "/api/v1/lineage")] * len(bundle["lineage"]["edges"])
        + [("PATCH", "/api/v1/tables (table tags)")] * len(bundle["tags"]["tables"])
        + [("GET+PATCH", "/api/v1/tables (column tags)")] * len(column_tables)
    )

    if dry_run:
        return {
            "status": "dry-run",
            "requests": len(planned),
            "by_endpoint": _count_by(planned),
            "sent": 0,
        }

    client = Pusher(base_url, token)
    results: Dict[str, int] = {}
    failures: List[str] = []

    def record(label: str, status: int, detail: Any) -> None:
        results[label] = results.get(label, 0) + 1
        if status >= 400 or status == 0:
            if len(failures) < 20:
                failures.append(f"{label}: HTTP {status} {str(detail)[:200]}")

    for classification in bundle["classifications"]["classifications"]:
        record("classifications", *client.put("/api/v1/classifications", classification))
    for tag in bundle["classifications"]["tags"]:
        record("tags", *client.put("/api/v1/tags", tag))
    record("glossaries", *client.put("/api/v1/glossaries", bundle["glossary"]["glossary"]))
    for term in bundle["glossary"]["terms"]:
        record("glossaryTerms", *client.put("/api/v1/glossaryTerms", term))
    for edge in bundle["lineage"]["edges"]:
        record("lineage", *client.put("/api/v1/lineage", edge))
    # Table-level tags: one patch per table, no lookup needed.
    for application in bundle["tags"]["tables"]:
        record("table_tags", *client.patch(
            f"/api/v1/tables/name/{application['fqn']}",
            [{"op": "add", "path": "/tags/-", "value": tag_label(t)}
             for t in application["tags"]],
        ))

    # Column-level tags and dlt descriptions: grouped by table, because OpenMetadata
    # has no per-column endpoint. A column tag is a JSON Patch against
    # `/columns/<index>/tags/-`, and the index depends on the column order the dbt
    # connector wrote — so the table has to be read before it can be patched. One GET
    # and one PATCH per table rather than one pair per column.
    by_table: Dict[str, List[Dict[str, Any]]] = {}
    for application in bundle["tags"]["columns"] + bundle["dlt"]["applications"]:
        if application["entity"] != "column":
            continue
        by_table.setdefault(application["table_fqn"], []).append(application)

    for table_fqn, applications in sorted(by_table.items()):
        status, table = client.get(
            f"/api/v1/tables/name/{table_fqn}?fields=columns,tags"
        )
        if status >= 400 or not isinstance(table, dict):
            record("column_tags", status, table)
            continue
        index_of = {
            str(column.get("name")): position
            for position, column in enumerate(table.get("columns") or [])
        }
        ops: List[Dict[str, Any]] = []
        missing = 0
        for application in applications:
            position = index_of.get(application["column"])
            if position is None:
                # The dbt connector has not ingested this column — or has ingested it
                # under different casing. Counted, never invented: patching a guessed
                # index tags the wrong column.
                missing += 1
                continue
            for tag in application["tags"]:
                ops.append({
                    "op": "add",
                    "path": f"/columns/{position}/tags/-",
                    "value": tag_label(tag),
                })
            description = application.get("description")
            existing = (table.get("columns") or [])[position].get("description")
            if description and not existing:
                # Only where the server has none. Overwriting a description somebody
                # curated in the UI is the data loss a unidirectional pipeline is
                # supposed to make impossible.
                ops.append({
                    "op": "add",
                    "path": f"/columns/{position}/description",
                    "value": description,
                })
        if missing:
            results["columns_absent_on_server"] = (
                results.get("columns_absent_on_server", 0) + missing
            )
        record("column_tags", *client.patch(f"/api/v1/tables/name/{table_fqn}", ops))

    bookkeeping = {"columns_absent_on_server"}
    return {
        "status": "fail" if failures else "ok",
        "requests": sum(v for k, v in results.items() if k not in bookkeeping),
        "by_endpoint": results,
        "failures": failures,
    }


def _count_by(planned: List[Tuple[str, str]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for _method, path in planned:
        counts[path] = counts.get(path, 0) + 1
    return counts


# ---------------------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------------------


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _serialise(payload: Any) -> str:
    """Stable bytes: sorted keys, two-space indent, trailing newline. `--check` is bytes."""
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


@dataclass
class Emission:
    files: Dict[Path, str] = field(default_factory=dict)
    changed: List[str] = field(default_factory=list)


def sync(slug: str, manifest_arg: Optional[str], check: bool,
         push: bool = False, dry_run: bool = False,
         with_warehouse: bool = False) -> Dict[str, Any]:
    use_case = use_case_dir(slug)
    if use_case is None:
        return {"status": "skip", "reason": f"no such use-case: {slug}"}

    cfg, reason = Config.load(use_case, slug)
    if cfg is None:
        return {"status": "skip", "reason": reason}

    manifest_path: Optional[Path] = None
    if manifest_arg:
        candidate = Path(manifest_arg)
        if candidate.exists():
            manifest_path = candidate
    else:
        candidate = use_case / "dbt_project/target/manifest.json"
        if candidate.exists():
            manifest_path = candidate

    man = Manifest.load(str(manifest_path)) if manifest_path else None
    if man is None and not cfg.dlt_warehouse:
        return {
            "status": "skip",
            "reason": "no manifest and no dlt_warehouse — run artifacts/refresh.sh",
        }

    relations = relation_index(man) if man else {}
    ontology = use_case / "ontology"
    index = _read_json(ontology / "index.json")
    column_memory = _read_json(ontology / "column-memory.json")
    annotations = _read_json(ontology / "column-annotations.json")

    glossary = build_glossary(index, column_memory, annotations, cfg, slug)
    classifications = build_classifications()
    tags = build_tag_applications(annotations, column_memory, relations, cfg)
    lineage = build_column_lineage(column_memory, relations, cfg)
    dlt = build_dlt_provenance(use_case, man, cfg, with_warehouse)

    bundle = {
        "glossary": glossary,
        "classifications": classifications,
        "tags": tags,
        "lineage": lineage,
        "dlt": dlt,
    }

    root = use_case / BUNDLE_DIR
    files: Dict[Path, str] = {
        root / "bundle/glossary.json": _serialise(glossary),
        root / "bundle/classifications.json": _serialise(classifications),
        root / "bundle/tag-applications.json": _serialise(tags),
        root / "bundle/column-lineage.json": _serialise(lineage),
        root / "bundle/dlt-provenance.json": _serialise(dlt),
        root / "ingestion/dbt.yaml": build_ingestion_config(
            use_case, slug, manifest_path, cfg
        ),
        root / "rdf/openmetadata-alignment.ttl": build_rdf_alignment(
            index, column_memory, lineage, relations, cfg, slug
        ),
        root / "knowledge/catalog.md": build_catalog_markdown(slug, cfg, bundle),
        root / "knowledge/mcp.md": build_mcp_markdown(slug, cfg),
    }

    changed: List[str] = []
    for path, content in sorted(files.items()):
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing == content:
            continue
        changed.append(str(path.relative_to(use_case)))
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    validation = validate_with_sdk(bundle)
    vocabulary = check_vocabulary()
    schema = check_against_pinned_spec(bundle)

    payload: Dict[str, Any] = {
        "status": "synced",
        "use_case": slug,
        "check": check,
        "service": cfg.service,
        "glossary": cfg.glossary,
        "concept_terms": sum(1 for t in glossary["terms"] if "iri" in t),
        "column_terms": sum(1 for t in glossary["terms"] if "iri" not in t),
        "unannotated_columns": len(glossary.get("unannotated_columns") or []),
        "classifications": len(classifications["classifications"]),
        "tag_definitions": len(classifications["tags"]),
        "column_tag_applications": len(tags["columns"]),
        "table_tag_applications": len(tags["tables"]),
        "lineage": lineage["stats"],
        "lineage_dropped": len(lineage["dropped"]["unresolved_source_models"]),
        "dlt": dlt["stats"],
        "dlt_evidence": dlt["evidence"],
        "validation": validation,
        "spec_check": schema,
        "vocabulary": vocabulary,
        "changed": changed,
    }

    if push:
        base_url = os.environ.get(SERVER_URL_ENV, "")
        token = os.environ.get(AUTH_TOKEN_ENV, "")
        if not base_url or not token:
            payload["push"] = {
                "status": "skip",
                "reason": f"set {SERVER_URL_ENV} and {AUTH_TOKEN_ENV} to push",
            }
        elif check:
            payload["push"] = {"status": "skip", "reason": "--check never pushes"}
        else:
            payload["push"] = push_bundle(bundle, base_url, token, dry_run)
    return payload


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--use-case", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--check", action="store_true",
                        help="write nothing; exit 1 if the bundle would change")
    parser.add_argument("--push", action="store_true",
                        help="DATA EGRESS: send the bundle to the server named by "
                             f"{SERVER_URL_ENV}")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --push, count the requests without sending any")
    parser.add_argument("--with-warehouse", action="store_true",
                        help="read the dlt warehouse named in openmetadata.yml for dlt "
                             "load-column evidence; off by default because a gitignored "
                             "warehouse makes the bundle differ between clones")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    payload = sync(args.use_case, args.manifest, args.check, args.push, args.dry_run,
                   args.with_warehouse)

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False))
    elif payload["status"] == "skip":
        print(f"skip  {args.use_case}: {payload['reason']}")
    else:
        lineage = payload["lineage"]
        print(
            f"{payload['concept_terms']} concept term(s), "
            f"{payload['column_terms']} column term(s), "
            f"{payload['classifications']} classification(s) / "
            f"{payload['tag_definitions']} tag(s); "
            f"{lineage['column_edges']} column lineage edge(s) across "
            f"{lineage['table_pairs']} table pair(s); "
            f"{payload['column_tag_applications']} column tag application(s)"
        )
        print(
            f"  service {payload['service']} · glossary {payload['glossary']} · "
            f"{payload['unannotated_columns']} conformed column(s) unannotated"
        )
        print(
            f"  gates: pinned spec {payload['spec_check']['status']} · "
            f"om vocabulary {payload['vocabulary']['status']} · "
            f"sdk models {payload['validation']['status']}"
        )
        for problem in (payload["spec_check"].get("problems", [])
                        + payload["vocabulary"].get("problems", [])):
            print(f"    {problem}")
        if payload["lineage_dropped"]:
            print(
                f"  {payload['lineage_dropped']} binding endpoint(s) resolved to no dbt "
                "node and were dropped (SQL parse artifacts)"
            )
        print(f"  dlt: {payload['dlt']['tables_carrying_dlt_columns']} table(s) with "
              f"load columns, {payload['dlt']['tables_tagged']} system table(s), "
              f"{payload['dlt']['column_applications']} column application(s) "
              f"[{', '.join(payload['dlt_evidence'])}]")
        for rel in payload["changed"]:
            print(f"  {'would change' if args.check else 'changed'} {rel}")
        if "push" in payload:
            push = payload["push"]
            print(f"  push: {push['status']} "
                  f"({push.get('reason') or push.get('requests', 0)} request(s))")
            for failure in push.get("failures", [])[:5]:
                print(f"    {failure}")

    if payload["status"] == "synced":
        for gate in ("validation", "spec_check", "vocabulary"):
            if payload[gate]["status"] == "fail":
                return 1
        if payload.get("push", {}).get("status") == "fail":
            return 1
        if args.check and payload["changed"]:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
