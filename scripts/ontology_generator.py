#!/usr/bin/env python3
"""Generate connector ontology extensions and domain topologies from the dbt project.

The ontology is *derived*, not maintained. Three artifacts already say everything a
connector extension needs to assert, and all three are kept current by other means:

  * `global_configs('all_available_sources')` — which connectors exist and which conformed
    concepts each supplies. Already the single source of truth, already enforced by
    tests/test_enhanza_connector_registry.py.
  * `manifest.json` — which models and sources actually exist. dbt writes it.
  * `scripts/dbt_column_lineage.py` — which source column became which conformed column,
    read out of the SQL by a parser rather than from documentation.

Writing the extensions by hand would create a fourth statement of the same facts, and a
fourth thing to drift. So they are generated, and hand edits are reverted on the next run.

The design follows the Building Topology Ontology's extension pattern
(https://w3id.org/bot#): a minimal core plus per-domain modules that attach by
rdfs:subClassOf. BOT's own alignment modules map one vocabulary onto another and are checked
by reading them; these map a vocabulary onto physical warehouse tables, so they can be
checked by running something. That is the point of the `conn:` vocabulary — every generated
class names a dbt model that either is in the manifest or is not.

Planned connectors get a stub. Their source schema is not known in this repository, so no
tables, columns, or mappings are written for them — an ontology that looks complete and maps
to nothing is worse than an obviously empty one. See rule 5.

Usage:
    python3 scripts/ontology_generator.py --use-case enhanza-analytics
    python3 scripts/ontology_generator.py --use-case enhanza-analytics --check
    python3 scripts/ontology_generator.py --use-case enhanza-analytics --format json
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

from _manifest import Manifest, die  # noqa: E402
import _miniyaml  # noqa: E402
import _paths  # noqa: E402
from _paths import REPO  # noqa: E402


def use_case_dir(slug: str) -> Path:
    """`_paths.require_use_case_dir` bound to this module's REPO; absence exits 2."""
    return _paths.require_use_case_dir(slug, REPO)

# The namespace a use-case gets when it has no `ontology/ontology.yml`. Only the first
# use-case ever relied on an implicit value; every use-case scaffolded since pins its own,
# because an IRI that changes when a default changes is not a stable identifier.
DEFAULT_NAMESPACE = "https://w3id.org/enhanza/"

NS_ERP = f"{DEFAULT_NAMESPACE}erp#"
NS_CRM = f"{DEFAULT_NAMESPACE}crm#"
NS_CONN = f"{DEFAULT_NAMESPACE}connector#"
NS_TOPO = f"{DEFAULT_NAMESPACE}topology#"

# Which core class each conformed concept realises. Explicit rather than derived from the
# name: `dim_accounting` is a Favrit ledger export and not an erp:Account, and a rule that
# maps every `dim_*` to a Classifier would get it wrong silently. A concept absent here is
# reported, not guessed at — the generator refuses to invent a classification.
CONCEPT_CLASS: Dict[str, str] = {
    # parties
    "dim_customers": "erp:Customer",
    "dim_suppliers": "erp:Supplier",
    "dim_employees": "erp:Employee",
    "dim_company": "erp:Organisation",
    "dim_user_locations": "erp:Organisation",
    # resources
    "dim_articles": "erp:Article",
    "dim_bundle_articles": "erp:BundleArticle",
    "dim_supplier_items": "erp:Article",
    "dim_assets_types": "erp:Asset",
    # classifiers
    "dim_accounts": "erp:Account",
    "dim_cost_centers": "erp:CostCenter",
    "dim_projects": "erp:Project",
    "dim_labels": "erp:Label",
    "dim_pricelists": "erp:PriceList",
    "dim_prices": "erp:PriceList",
    "dim_stockpoints": "erp:StockPoint",
    "dim_voucher_series": "erp:VoucherSeries",
    "dim_expenses": "erp:Classifier",
    "dim_meta_data": "erp:Classifier",
    "dim_ratings": "erp:Classifier",
    "dim_accounting": "erp:Classifier",
    "dim_supplier_invoice_files": "erp:Classifier",
    # periods
    "dim_financial_years": "erp:FinancialYear",
    "fact_locked_period": "erp:LockedPeriod",
    # documents
    "fact_invoices": "erp:Invoice",
    "fact_supplier_invoices": "erp:SupplierInvoice",
    "fact_orders": "erp:Order",
    "fact_purchase_orders": "erp:PurchaseOrder",
    "fact_offers": "erp:Offer",
    "fact_contracts": "erp:Contract",
    "fact_vouchers": "erp:Voucher",
    "fact_production_orders": "erp:ProductionOrder",
    "fact_assets": "erp:Asset",
    "fact_work_orders": "erp:Document",
    # line items
    "fact_invoice_rows": "erp:LineItem",
    "fact_supplier_invoice_rows": "erp:LineItem",
    "fact_order_rows": "erp:LineItem",
    "fact_offer_rows": "erp:LineItem",
    "fact_contract_rows": "erp:LineItem",
    "fact_asset_rows": "erp:LineItem",
    "fact_opportunity_rows": "crm:OpportunityLine",
    # events
    "fact_invoice_payments": "erp:Payment",
    "fact_salary_transactions": "erp:SalaryTransaction",
    "fact_absence_transactions": "erp:AbsenceTransaction",
    "fact_attendance_transactions": "erp:AttendanceTransaction",
    "fact_time_reporting_registrations": "erp:TimeReportingRegistration",
    "fact_stockbalance": "erp:StockBalance",
    "fact_stocktakings": "erp:Stocktaking",
    "fact_incoming_goods": "erp:IncomingGoods",
    "fact_budgets": "erp:Budget",
    "fact_employee_wages": "erp:SalaryTransaction",
    "fact_employee_schedules": "erp:Event",
    "fact_invoice_accruals": "erp:Event",
    "fact_supplier_invoice_accruals": "erp:Event",
    "fact_rolling_sum": "erp:Event",
    # crm
    "fact_opportunities": "crm:Opportunity",
    "fact_activities": "crm:Activity",
    "fact_appointments": "crm:Appointment",
}

# Conformed column -> core property, with the class family the rule is valid for.
#
# Class-aware on purpose. A first version keyed on the column name alone asserted
# `ArticleNumber -> erp:partyNumber`, which says an Article is a Party — semantically wrong,
# and produced by a rule that looked reasonable in the abstract. `SupplierNumber` shows the
# same hazard from the other side: on `dim_suppliers` it identifies the party, on
# `dim_articles` it is the supplier's code *for that article*. A column name is not a
# meaning until you know what it is a column of.
#
# `None` means the rule holds for any class. Anything genuinely ambiguous is left out
# entirely rather than guessed — an absent mapping costs a reader one lookup, a wrong one
# costs them a wrong answer.
COLUMN_PROPERTY: Dict[str, Tuple[str, Optional[Tuple[str, ...]]]] = {
    "OrgId":         ("erp:orgId", None),
    "OrgName":       ("erp:partyName", ("erp:Organisation", "erp:Customer", "erp:Supplier", "erp:Employee")),
    "CustomerNumber": ("erp:partyNumber", ("erp:Customer",)),
    "SupplierNumber": ("erp:partyNumber", ("erp:Supplier",)),
    "EmployeeNumber": ("erp:partyNumber", ("erp:Employee",)),
    "ArticleNumber":  ("erp:resourceNumber", ("erp:Article", "erp:BundleArticle")),
    "ArticleName":    ("erp:resourceName", ("erp:Article", "erp:BundleArticle")),
    "DocumentNumber": ("erp:documentNumber", None),
    "InvoiceNumber":  ("erp:documentNumber", None),
    "OrderNumber":    ("erp:documentNumber", None),
    "InvoiceDate":    ("erp:documentDate", None),
    "OrderDate":      ("erp:documentDate", None),
    "Total":          ("erp:amount", None),
    "TotalAmount":    ("erp:amount", None),
    "Amount":         ("erp:amount", None),
    "Quantity":       ("erp:quantity", None),
    "Currency":       ("erp:currency", None),
    "CurrencyCode":   ("erp:currency", None),
    "Active":         ("erp:isActive", None),
    "isActive":       ("erp:isActive", None),
}


def property_for(column: str, core_class: Optional[str]) -> Optional[str]:
    """The core property a column realises, or None when no rule applies to this class."""
    rule = COLUMN_PROPERTY.get(column)
    if not rule:
        return None
    prop, valid_for = rule
    if valid_for is None:
        return prop
    return prop if core_class in valid_for else None

KIND_CLASS = {
    "erp": "conn:ERPConnector",
    "crm": "conn:CRMConnector",
    "commerce": "conn:CommerceConnector",
}


@dataclass
class OntologyConfig:
    """Per-use-case settings, from `ontology/ontology.yml`.

    Everything above this line is the *shared* ERP/CRM vocabulary — it describes what an
    invoice and a customer are, which does not change because a second use-case exists. What
    a use-case owns is its IRI namespace and whatever concepts its own domain adds. Those two
    live in a file next to the ontology rather than in this script, so onboarding a use-case
    is a scaffold rather than a patch to shared code.
    """

    namespace: str = DEFAULT_NAMESPACE
    concept_class: Dict[str, str] = field(default_factory=lambda: dict(CONCEPT_CLASS))
    title: str = ""

    @property
    def erp(self) -> str:
        return f"{self.namespace}erp#"

    @property
    def crm(self) -> str:
        return f"{self.namespace}crm#"

    @property
    def conn(self) -> str:
        return f"{self.namespace}connector#"

    @property
    def topo(self) -> str:
        return f"{self.namespace}topology#"

    def connector_ns(self, key: str) -> str:
        return f"{self.namespace}connector/{key.replace('_', '-')}#"

    @property
    def col(self) -> str:
        return f"{self.namespace}column#"


def read_config(ontology: Path, slug: str) -> OntologyConfig:
    path = ontology / "ontology.yml"
    if not path.exists():
        return OntologyConfig(title=slug)
    data = _miniyaml.load(path.read_text(encoding="utf-8")) or {}
    namespace = str(data.get("namespace") or DEFAULT_NAMESPACE)
    if not namespace.endswith(("#", "/")):
        namespace += "/"
    merged = dict(CONCEPT_CLASS)
    # Use-case additions layer over the shared map. Overriding a shared concept is allowed
    # and occasionally right — the same `dim_accounts` is a ledger account in one domain and
    # a login in another — so this is a merge, not a rejection.
    for concept, core in (data.get("concept_classes") or {}).items():
        merged[str(concept)] = str(core)
    return OntologyConfig(
        namespace=namespace,
        concept_class=merged,
        title=str(data.get("title") or slug),
    )


@dataclass
class ConnectorSpec:
    key: str
    name: str
    kind: str
    status: str
    # Whether the raw dataset this connector reads actually exists yet. A *different*
    # fact from `status`, and conflating them is a defect: `status` says the connector is
    # wired into the dbt registry (`test_catalogue_and_registry_agree` pins it to
    # `global_configs.sql`), and `planned` is tested to mean nothing is known at all — no
    # source tables, no models, no mappings. A connector whose adapters are written and
    # whose ingestion job has not run is in neither state, and forcing it into `planned`
    # asserts its models do not exist while they sit in the manifest. `landed` is the
    # default because it is the state every connector here was in before one was not.
    ingestion: str = "landed"
    region: Optional[str] = None
    expected_concepts: List[str] = field(default_factory=list)
    # filled from the project, never from the catalogue
    concepts: List[str] = field(default_factory=list)
    default_currency: Optional[str] = None
    models: Dict[str, str] = field(default_factory=dict)   # concept -> dbt model
    sources: Dict[str, str] = field(default_factory=dict)  # concept -> source table
    mappings: Dict[str, List[Tuple[str, str, str]]] = field(default_factory=dict)


# ---------------------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------------------


def read_catalogue(path: Path) -> List[ConnectorSpec]:
    data = _miniyaml.load(path.read_text(encoding="utf-8"))
    out: List[ConnectorSpec] = []
    for row in data.get("connectors", []) or []:
        out.append(
            ConnectorSpec(
                key=row["key"],
                name=row.get("name", row["key"]),
                kind=row.get("kind", "erp"),
                status=row.get("status", "planned"),
                ingestion=str(row.get("ingestion", "landed")),
                region=row.get("region"),
                expected_concepts=list(row.get("expected_concepts", []) or []),
            )
        )
    return out


def read_registry(project: Path) -> Dict[str, Dict[str, Any]]:
    """Parse `all_available_sources` — the project's own answer to what exists.

    A text parse for the same reason tests/test_enhanza_connector_registry.py uses one:
    the alternative is booting dbt, which needs a warehouse profile CI does not have.
    """
    macro = project / "macros/config/global_configs.sql"
    if not macro.exists():
        return {}
    text = macro.read_text(encoding="utf-8")
    marker = "'all_available_sources': {"
    if marker not in text:
        return {}
    body = text[text.index(marker) + len(marker):]
    depth = 1
    for i, ch in enumerate(body):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                body = body[:i]
                break

    out: Dict[str, Dict[str, Any]] = {}
    current: Optional[str] = None
    in_included = False
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("{#") or line.startswith("-#}"):
            continue
        if not in_included:
            match = re.match(r"^'([a-z_0-9]+)':\s*\{$", line)
            if match:
                current = match.group(1)
                out[current] = {"concepts": [], "attrs": {}}
                continue
        if line.startswith("'included_models': ["):
            in_included = True
            continue
        if in_included:
            if line.startswith("]"):
                in_included = False
                continue
            match = re.match(r"^'([a-z_0-9]+)',?$", line)
            if match and current:
                out[current]["concepts"].append(match.group(1))
            continue
        match = re.match(r"^'([a-z_0-9]+)':\s*'([^']*)'", line)
        if match and current:
            out[current]["attrs"][match.group(1)] = match.group(2)
    return out


def enrich_from_project(
    specs: List[ConnectorSpec],
    project: Path,
    manifest_path: Optional[Path],
    cfg: Optional[OntologyConfig] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """Fill each implemented connector from the registry, manifest, and column lineage."""
    cfg = cfg or OntologyConfig()
    registry = read_registry(project)
    problems: List[str] = []
    lineage_stats: Dict[str, Any] = {}

    by_key = {s.key: s for s in specs}
    for key in sorted(set(registry) - set(by_key)):
        problems.append(
            f"registry has connector '{key}' with no row in connectors.yml — add it"
        )
    for spec in specs:
        if spec.status == "implemented" and spec.key not in registry:
            problems.append(
                f"connectors.yml marks '{spec.key}' implemented but it is not in "
                f"all_available_sources — either register it or set status: planned"
            )

    for spec in specs:
        entry = registry.get(spec.key)
        if not entry:
            continue
        spec.concepts = sorted(entry["concepts"])
        spec.default_currency = entry["attrs"].get("default_currency")

    if manifest_path and manifest_path.exists():
        man = Manifest.load(str(manifest_path))
        by_name = {n.get("name"): n for n in man.nodes.values() if n.get("resource_type") == "model"}
        src_by_uid = {
            uid: f"{n.get('source_name')}.{n.get('name')}" for uid, n in man.sources.items()
        }

        # A concept is *unified* when the project ships an `erp_bi_<concept>` model to union
        # the sources. Only those require a `<source>_erp_bi_<concept>` adapter — the rule
        # tests/test_enhanza_connector_registry.py enforces. A connector may also claim a
        # concept it serves natively from its own BI layer with no adapter and no union, and
        # demanding an adapter for those reported 29 defects that were not defects.
        union_concepts = {
            name[len("erp_bi_"):].removesuffix("_staging")
            for name in by_name
            if name.startswith("erp_bi_")
        }

        for spec in specs:
            for concept in spec.concepts:
                candidates = [f"{spec.key}_erp_bi_{concept}"] if concept in union_concepts else []
                # Connector-native shapes, in the order the project uses them.
                candidates += [
                    f"{spec.key}_bi_{concept}",
                    f"{spec.key}_bi_{concept}_staging",
                    f"{spec.key}_erp_bi_{concept}",
                ]
                node = None
                model_name = ""
                for candidate in candidates:
                    if candidate in by_name:
                        node, model_name = by_name[candidate], candidate
                        break
                if node is None:
                    if concept in union_concepts:
                        problems.append(
                            f"{spec.key} claims unified concept '{concept}' but no "
                            f"{spec.key}_erp_bi_{concept} adapter is in the manifest"
                        )
                    continue
                spec.models[concept] = model_name
                tables = sorted(
                    {
                        src_by_uid[u]
                        for u in node.get("depends_on", {}).get("nodes", []) or []
                        if u in src_by_uid
                    }
                )
                if tables:
                    spec.sources[concept] = ", ".join(tables)

        lineage_stats = _attach_mappings(specs, man, cfg)

    return problems, lineage_stats


def _attach_mappings(
    specs: List[ConnectorSpec], man: Manifest, cfg: OntologyConfig
) -> Dict[str, Any]:
    """Column mappings, read from the parsed SQL rather than from documentation."""
    try:
        import dbt_column_lineage as lineage_mod
    except ImportError:  # pragma: no cover - ships beside this file
        return {"available": False, "reason": "dbt_column_lineage.py not importable"}
    if lineage_mod.sqlglot is None:
        return {"available": False, "reason": "sqlglot not installed"}

    lineage = lineage_mod.build_lineage(man)
    by_model: Dict[str, List[Any]] = {}
    for edge in lineage["edges"]:
        by_model.setdefault(edge.model, []).append(edge)

    for spec in specs:
        for concept, model_name in spec.models.items():
            core_class = cfg.concept_class.get(concept)
            rows: List[Tuple[str, str, str]] = []
            for edge in by_model.get(model_name, []):
                if not edge.upstream_column or edge.column in ("*", "(macro)"):
                    continue
                prop = property_for(edge.column, core_class)
                if not prop:
                    continue
                rows.append((prop, edge.upstream_column, edge.kind))
            if rows:
                spec.mappings[concept] = sorted(set(rows))
    return {
        "available": True,
        "models_parsed": lineage["parsed"],
        "models_macro_only": lineage["macro_only"],
        "models_parse_failed": lineage["parse_failed"],
    }


# ---------------------------------------------------------------------------------------
# Turtle emission
# ---------------------------------------------------------------------------------------


def _local(concept: str) -> str:
    """`fact_invoice_rows` -> `InvoiceRow`; the class name a reader would expect."""
    stem = re.sub(r"^(dim|fact)_", "", concept)
    parts = [p for p in stem.split("_") if p]
    name = "".join(p[:1].upper() + p[1:] for p in parts)
    return name[:-1] if name.endswith("s") and not name.endswith("ss") else name


def _words(local: str) -> str:
    """`InvoiceRow` -> `Invoice Row`; the class name spelled the way core/*.ttl spells it.

    A rendering of the identifier, not a lookup of the core class's label. Reading
    `core/*.ttl` would need an RDF parser, and rdflib is optional here — so the generator
    would acquire a dependency to restate a fact it already holds.
    """
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", local)


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def render_connector(spec: ConnectorSpec, cfg: Optional[OntologyConfig] = None) -> str:
    cfg = cfg or OntologyConfig()
    ns = cfg.connector_ns(spec.key)
    lines: List[str] = [
        f"@prefix {spec.key}: <{ns}> .",
        f"@prefix conn:    <{cfg.conn}> .",
        f"@prefix erp:     <{cfg.erp}> .",
        f"@prefix crm:     <{cfg.crm}> .",
        "@prefix owl:     <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdfs:    <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "",
        "# GENERATED by scripts/ontology_generator.py — do not edit.",
        "# Fix the dbt project or ontology/connectors.yml; this file is rewritten from them.",
        "",
        f"<{ns}> a owl:Ontology ;",
        f'    dcterms:title "{_esc(spec.name)} connector extension"@en ;',
        f"    owl:imports <{cfg.erp}>, <{cfg.conn}> ;",
    ]
    if spec.status == "planned":
        lines.append(
            '    rdfs:comment """PLANNED. This connector is named in the catalogue and its '
            "source schema is not known in this repository, so no tables, columns, or "
            "mappings are asserted here. The concepts below are an expectation about scope, "
            'not a claim that the connector supplies them."""@en ;'
        )
    lines[-1] = lines[-1].rstrip(" ;") + " ."
    lines.append("")

    # ---- the connector individual
    lines += [
        f"{spec.key}:connector a {KIND_CLASS.get(spec.kind, 'conn:Connector')} ;",
        f'    rdfs:label "{_esc(spec.name)}"@en ;',
        f'    conn:registryKey "{spec.key}" ;',
        f'    conn:enableVar "is_{spec.key}_enabled" ;',
        f'    conn:status "{spec.status}" ;',
    ]
    if spec.region:
        lines.append(f'    dcterms:spatial "{spec.region}" ;')
    if spec.default_currency:
        lines.append(f'    conn:defaultCurrency "{spec.default_currency}" ;')
    lines[-1] = lines[-1].rstrip(" ;") + " ."
    lines.append("")

    concepts = spec.concepts if spec.status == "implemented" else spec.expected_concepts
    unclassified: List[str] = []

    for concept in concepts:
        core = cfg.concept_class.get(concept)
        if not core:
            unclassified.append(concept)
            continue
        local = _local(concept)
        cls = f"{spec.key}:{local}"
        lines.append(f"{cls} a owl:Class ;")
        lines.append(f"    rdfs:subClassOf {core} ;")
        # Qualified by the connector, because these classes collide by design: ten
        # connectors each declare an `Account`, and ten classes labelled "Account" tell a
        # reader — or a BI picker — less than no label at all.
        lines.append(f'    rdfs:label "{_esc(spec.name)} {_words(local)}"@en ;')
        lines.append(f"    conn:conformsTo {core} ;")
        lines.append(f"    conn:providedBy {spec.key}:connector ;")
        model = spec.models.get(concept)
        if model:
            lines.append(f'    conn:dbtModel "{model}" ;')
            lines.append(f'    conn:dbtPackage "{spec.key}" ;')
        source = spec.sources.get(concept)
        if source:
            lines.append(f'    conn:sourceTable "{_esc(source)}" ;')
        if spec.status == "planned":
            lines.append('    rdfs:comment "[NEEDS INPUT] source table unknown"@en ;')
        lines[-1] = lines[-1].rstrip(" ;") + " ."

        for prop, src_col, kind in spec.mappings.get(concept, []):
            # The source column is part of the identity, not decoration. Two columns can
            # legitimately realise one property — an invoice with both a document date and a
            # due date — and keying the node on the property alone silently collapses them
            # into one Mapping whose sourceColumn is whichever was emitted last.
            node = (
                f"{spec.key}:{_local(concept)}-"
                f"{re.sub(r'[^A-Za-z0-9]+', '', prop.split(':')[-1])}-"
                f"{re.sub(r'[^A-Za-z0-9]+', '', src_col)}"
            )
            lines.append(f"{cls} conn:hasMapping {node} .")
            lines.append(f"{node} a conn:Mapping ;")
            lines.append(f"    conn:mapsToProperty {prop} ;")
            lines.append(f'    conn:sourceColumn "{_esc(src_col)}" ;')
            lines.append(f'    conn:transform "{kind}" .')
        lines.append("")

    if unclassified:
        lines.append("# Concepts with no core class in CONCEPT_CLASS — classify them in")
        lines.append("# scripts/ontology_generator.py rather than letting the generator guess:")
        for concept in unclassified:
            lines.append(f"#   {concept}")
        lines.append("")

    return "\n".join(lines)


def render_topology(specs: List[ConnectorSpec], cfg: Optional[OntologyConfig] = None) -> str:
    """Which connectors realise each conformed concept — the topology of the domain.

    This is the view no single connector file holds and the one that decides whether a
    number is comparable across tenants: a concept supplied by one connector cannot be
    benchmarked, and a concept supplied by seven is where conformance actually has to hold.
    """
    cfg = cfg or OntologyConfig()
    by_concept: Dict[str, List[ConnectorSpec]] = {}
    for spec in specs:
        for concept in (spec.concepts if spec.status == "implemented" else spec.expected_concepts):
            by_concept.setdefault(concept, []).append(spec)

    lines: List[str] = [
        f"@prefix topo: <{cfg.topo}> .",
        f"@prefix conn: <{cfg.conn}> .",
        f"@prefix erp:  <{cfg.erp}> .",
        f"@prefix crm:  <{cfg.crm}> .",
        "@prefix owl:  <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "",
        "# GENERATED by scripts/ontology_generator.py — do not edit.",
        "",
        f"<{cfg.topo}> a owl:Ontology ;",
        '    rdfs:comment """Concept coverage across connectors. Generated from the registry',
        "and the connector catalogue: for each conformed concept, which connectors realise it",
        "and which core class it belongs to. A concept with one supplier is not yet conformed;",
        'a concept with none is a gap in the model, not in the data."""@en .',
        "",
    ]
    for concept in sorted(by_concept):
        core = cfg.concept_class.get(concept, "owl:Thing")
        node = f"topo:{_local(concept)}"
        impl = [s for s in by_concept[concept] if s.status == "implemented"]
        planned = [s for s in by_concept[concept] if s.status != "implemented"]
        lines.append(f"{node} a conn:Concept ;")
        lines.append(f'    rdfs:label "{concept}" ;')
        lines.append(f"    conn:conformsTo {core} ;")
        for spec in impl:
            lines.append(f"    conn:providedBy <{cfg.connector_ns(spec.key)}connector> ;")
        for spec in planned:
            lines.append(f"    conn:providedBy <{cfg.connector_ns(spec.key)}connector> ;")
        lines.append(f'    rdfs:comment "{len(impl)} implemented, {len(planned)} planned" ;')
        lines[-1] = lines[-1].rstrip(" ;") + " ."
        lines.append("")
    return "\n".join(lines)


def read_annotations(ontology: Path) -> List[Dict[str, Any]]:
    """The column annotations, if a use-case has any.

    Absent is the normal state for a fresh use-case, and it is not an error: the ontology
    still describes every concept and connector. What it loses is the layer that says what
    a column *means*, which is the layer BI and an MCP client need most.
    """
    path = ontology / "column-annotations.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return list(data.get("columns") or [])


def render_column_semantics(annotations: List[Dict[str, Any]], cfg: OntologyConfig) -> str:
    """What each conformed column means, as assertions rather than as a table.

    `concept-coverage.ttl` says which connectors supply a concept; this says what the
    columns of those concepts *are* — the facet set an agent needs before it writes
    `SUM(...)` over one of them. Unlike the rest of the ontology it is not derived from the
    manifest: additivity and PII are decisions, so the source is the hand-authored
    `annotations.yml` and this file is its RDF projection.

    The vocabulary is declared inline rather than assumed, because a consumer that meets
    `conn:additivity` for the first time has no other place to look it up.
    """
    lines: List[str] = [
        f"@prefix col:  <{cfg.col}> .",
        f"@prefix conn: <{cfg.conn}> .",
        f"@prefix topo: <{cfg.topo}> .",
        "@prefix owl:  <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .",
        "",
        "# GENERATED by scripts/ontology_generator.py from ontology/annotations.yml — do not edit.",
        "",
        f"<{cfg.col}> a owl:Ontology ;",
        '    rdfs:comment """What each conformed column means. A column carries independent',
        "facets — role, additivity, PII class, unit, closed domain — because it is several",
        "things at once and no single hierarchy can hold all of them. Additivity and PII are",
        "decisions recorded by a human, not derivations: a measure summed at the wrong grain",
        'double-counts while every test passes."""@en .',
        "",
        "conn:ConformedColumn a owl:Class ;",
        '    rdfs:label "Conformed column"@en ;',
        '    rdfs:comment "A column whose meaning is the same in every connector that '
        'supplies it."@en .',
        "",
    ]
    for prop, label, comment in (
        ("role", "role", "identifier, measure, dimension, timestamp, flag, or text"),
        ("additivity", "additivity",
         "additive, semi-additive, or non-additive — whether SUM() over this column is "
         "meaningful, and across which dimensions"),
        ("pii", "PII class",
         "none, direct, quasi, or indirect — the remedies differ, so the class is recorded "
         "rather than a boolean"),
        ("unit", "unit", "what the number counts: currency, quantity, percent, duration"),
        ("domainValue", "closed-domain value", "one permitted value of a closed domain"),
        ("domainSource", "closed-domain source",
         "where the permitted values were read from; an enum nobody can cite is invented"),
        ("carriedBy", "carried by", "how many connectors supply this column"),
    ):
        kind = "owl:DatatypeProperty"
        lines.append(f"conn:{prop} a {kind} ;")
        lines.append(f'    rdfs:label "{label}"@en ;')
        lines.append(f'    rdfs:comment "{_esc(comment)}"@en ;')
        lines.append("    rdfs:domain conn:ConformedColumn .")
        lines.append("")

    for row in sorted(annotations, key=lambda r: str(r.get("column", ""))):
        name = str(row.get("column", ""))
        if not name:
            continue
        lines.append(f"col:{name} a conn:ConformedColumn ;")
        lines.append(f'    rdfs:label "{_esc(name)}"@en ;')
        lines.append(f'    conn:role "{_esc(str(row.get("role") or ""))}" ;')
        if row.get("additivity"):
            lines.append(f'    conn:additivity "{_esc(str(row["additivity"]))}" ;')
        if row.get("unit"):
            lines.append(f'    conn:unit "{_esc(str(row["unit"]))}" ;')
        lines.append(f'    conn:pii "{_esc(str(row.get("pii") or "none"))}" ;')
        for concept in sorted(row.get("concepts") or []):
            lines.append(f"    conn:realises topo:{_local(concept)} ;")
        domain = row.get("domain") or None
        if domain:
            for value in domain.get("values") or []:
                lines.append(f'    conn:domainValue "{_esc(str(value))}" ;')
            lines.append(f'    conn:domainSource "{_esc(str(domain.get("source") or ""))}" ;')
        lines.append(
            f'    conn:carriedBy "{int(row.get("carried_by_count") or 0)}"^^xsd:integer ;')
        lines.append(f'    skos:definition "{_esc(str(row.get("definition") or ""))}"@en ;')
        lines[-1] = lines[-1].rstrip(" ;") + " ."
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------
# The machine-facing projection
# ---------------------------------------------------------------------------------------

# Competency question -> the index key that answers it, and the MCP tool it becomes. Stated
# here rather than in prose because a server is going to read it: a tool whose backing key
# disappears should break a test, not a request at runtime.
MCP_TOOLS: Tuple[Tuple[str, str, str], ...] = (
    ("list_connectors", "connectors",
     "Every source system, its status, its enable var, and what it supplies."),
    ("describe_concept", "concepts",
     "One conformed concept: its core class and which connectors realise it."),
    ("locate_model", "models",
     "The dbt model and source tables behind a (connector, concept) pair."),
    ("resolve_column", "mappings",
     "Which source column realises a conformed property, per connector, and how."),
    ("coverage_gaps", "gaps",
     "Concepts with a single supplier, and planned concepts nothing supplies yet."),
    ("describe_column", "column_semantics",
     "What one conformed column means: its role, whether SUM() over it is meaningful, "
     "its PII class, its unit, and its closed domain if it has one."),
)


def render_index(specs: List[ConnectorSpec], cfg: OntologyConfig, slug: str,
                 lineage: Dict[str, Any],
                 annotations: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """A flat JSON projection of the same facts the Turtle asserts.

    The Turtle is normative; this is a read-optimised view of it. Both come out of one pass
    over one set of inputs, so neither can lead the other, and
    `test_index_and_turtle_agree_on_every_model` fails if they ever disagree.

    Why a second artifact at all: the consumer is a server answering one question per call,
    and every one of the competency questions is a lookup in a list of like-shaped records.
    Serving those from Turtle means shipping an RDF parser and a query engine to answer what
    a dict answers directly — and `rdflib` is optional in this repository, so an MCP server
    built on it would fail to start wherever the parser is absent. Five uniform record lists
    also serialise straight to TOON, which is what carries them into a model's context.

    Deliberately *not* JSON-LD. A `@context` that covered these keys honestly would have to
    reify `models` and `mappings` into graph shapes they do not have, and one that covered
    only the prefixes would parse while dropping nearly every statement — a file that looks
    like RDF and asserts almost nothing is worse than one that never claimed to be.
    """
    connectors: List[Dict[str, Any]] = []
    models: List[Dict[str, Any]] = []
    mappings: List[Dict[str, Any]] = []

    for spec in sorted(specs, key=lambda s: s.key):
        concepts = spec.concepts if spec.status == "implemented" else spec.expected_concepts
        connectors.append({
            "key": spec.key,
            "id": f"{cfg.connector_ns(spec.key)}connector",
            "label": spec.name,
            "kind": spec.kind,
            "status": spec.status,
            "ingestion": spec.ingestion,
            "region": spec.region,
            "enable_var": f"is_{spec.key}_enabled",
            "default_currency": spec.default_currency,
            "concepts": list(concepts),
        })
        for concept in concepts:
            core = cfg.concept_class.get(concept)
            if not core:
                continue
            model = spec.models.get(concept)
            if model:
                models.append({
                    "connector": spec.key,
                    "concept": concept,
                    "core_class": core,
                    "class": f"{cfg.connector_ns(spec.key)}{_local(concept)}",
                    "dbt_model": model,
                    "source_tables": [
                        t.strip() for t in spec.sources.get(concept, "").split(",") if t.strip()
                    ],
                })
            for prop, src_col, kind in spec.mappings.get(concept, []):
                mappings.append({
                    "connector": spec.key,
                    "concept": concept,
                    "core_class": core,
                    "property": prop,
                    "source_column": src_col,
                    "transform": kind,
                })

    by_concept: Dict[str, Dict[str, List[str]]] = {}
    for spec in specs:
        bucket = "implemented_by" if spec.status == "implemented" else "planned_by"
        for concept in (spec.concepts if spec.status == "implemented" else spec.expected_concepts):
            by_concept.setdefault(concept, {"implemented_by": [], "planned_by": []})
            by_concept[concept][bucket].append(spec.key)

    concepts_out: List[Dict[str, Any]] = []
    for concept in sorted(by_concept):
        entry = by_concept[concept]
        concepts_out.append({
            "concept": concept,
            "id": f"{cfg.topo}{_local(concept)}",
            "core_class": cfg.concept_class.get(concept),
            "implemented_by": sorted(entry["implemented_by"]),
            "planned_by": sorted(entry["planned_by"]),
            "supplier_count": len(entry["implemented_by"]),
        })

    # The same facets the column-semantics Turtle asserts, flattened into the record list an
    # MCP tool answers from. `id` is the IRI, so a client that wants the RDF can follow it.
    semantics = [
        {
            "column": row.get("column"),
            "id": f"{cfg.col}{row.get('column')}",
            "role": row.get("role"),
            "additivity": row.get("additivity"),
            "unit": row.get("unit"),
            "pii": row.get("pii"),
            "definition": row.get("definition"),
            "domain": row.get("domain"),
            "concepts": list(row.get("concepts") or []),
            "connectors": list(row.get("connectors") or []),
            "carried_by_count": row.get("carried_by_count"),
        }
        for row in sorted(annotations or [], key=lambda r: str(r.get("column", "")))
    ]

    # A concept one connector supplies is not conformed yet — a number drawn from it cannot
    # be compared across tenants, which is the whole reason the conformed layer exists. The
    # index states that rather than leaving every consumer to recompute it.
    gaps = [
        {
            "concept": c["concept"],
            "reason": "single supplier" if c["supplier_count"] == 1 else "no supplier yet",
            "implemented_by": c["implemented_by"],
            "planned_by": c["planned_by"],
        }
        for c in concepts_out
        if c["supplier_count"] <= 1
    ]

    return {
        "use_case": slug,
        "title": cfg.title,
        "normative_source": "ontology/connectors/*.ttl and ontology/topology/*.ttl",
        "generated_by": "scripts/ontology_generator.py",
        "prefixes": {
            "erp": cfg.erp, "crm": cfg.crm, "conn": cfg.conn, "topo": cfg.topo,
        },
        "provenance": {
            "column_lineage_available": bool(lineage.get("available")),
            "models_parsed": lineage.get("models_parsed"),
            "models_macro_only": lineage.get("models_macro_only"),
            "models_parse_failed": lineage.get("models_parse_failed"),
            "annotated_columns": len(semantics),
        },
        "mcp_tools": [
            {"tool": tool, "backed_by": key, "answers": doc} for tool, key, doc in MCP_TOOLS
        ],
        "connectors": connectors,
        "concepts": concepts_out,
        "models": models,
        "mappings": mappings,
        "gaps": gaps,
        "column_semantics": semantics,
    }


# ---------------------------------------------------------------------------------------
# Graphify fragment
# ---------------------------------------------------------------------------------------


def build_graphify_fragment(
    specs: List[ConnectorSpec],
    cfg: OntologyConfig,
    use_case: Path,
    manifest_path: Optional[Path],
) -> Dict[str, Any]:
    """The connector/concept topology as a graphify extraction fragment.

    Built from the same in-memory specs that render the Turtle and `index.json`, never by
    re-parsing the Turtle: rdflib is optional in this repository, and a parser dependency
    to restate facts the generator already holds is the trade `index.json` exists to
    avoid. graphify itself never sees these facts either way — its detector puts `.ttl`
    in no category at all, so without this fragment the topology is invisible to the
    graph the Graphify-first rule makes agents orient with.

    Node ids reuse `dbt_manifest_to_graphify.node_id()`, so `implements` edges land on
    the model nodes the dbt merge already upgraded — and the same ordering rule follows:
    a `graphify update` after this merge deletes everything it added.

    Deliberately absent: edges to the column-contract nodes `dbt_column_memory.py`
    merges. An edge whose endpoint is missing would make `build_merge` mint a bare stub
    node silently, and both node families already edge the same adapter models, so the
    contract sits two hops away without asserting anything new.
    """
    import dbt_manifest_to_graphify as emitter

    ontology = use_case / "ontology"
    topo_rel = emitter._rel(ontology / "topology" / "concept-coverage.ttl")

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    blank = {
        "source_location": None, "source_url": None, "captured_at": None,
        "author": None, "contributor": None,
    }

    def edge(source: str, target: str, relation: str) -> None:
        edges.append({
            "source": source,
            "target": target,
            "relation": relation,
            "confidence": "EXTRACTED",
            "confidence_score": 1.0,
            "source_file": None,
            "source_location": None,
            "weight": 1.0,
        })

    # Model name -> the graph's own node id, through the dbt emitter's path map. Resolved
    # from the manifest rather than from a naming rule so a packages/ model cannot land on
    # a root-model id — the exact drift `package_prefixes` exists to prevent.
    model_gid: Dict[str, str] = {}
    if manifest_path and manifest_path.exists():
        man = Manifest.load(str(manifest_path))
        project_root = use_case / "dbt_project"
        for parent in manifest_path.resolve().parents:
            if (parent / "dbt_project.yml").exists():
                project_root = parent
                break
        prefixes = emitter.package_prefixes(man, project_root)
        project_rel = emitter._rel(project_root)
        for mnode in man.nodes.values():
            if mnode.get("resource_type") != "model":
                continue
            path = emitter.model_source_file(mnode, man, project_rel, prefixes)
            model_gid[mnode.get("name", "")] = emitter.node_id(path)

    # One node per conformed concept, keyed to the topology file that asserts it —
    # the entity form node_id() gives symbols that live inside a shared file.
    by_concept: Dict[str, Dict[str, List[str]]] = {}
    for spec in specs:
        bucket = "implemented_by" if spec.status == "implemented" else "planned_by"
        for concept in (spec.concepts if spec.status == "implemented" else spec.expected_concepts):
            by_concept.setdefault(concept, {"implemented_by": [], "planned_by": []})
            by_concept[concept][bucket].append(spec.key)

    concept_ids: Dict[str, str] = {}
    for concept in sorted(by_concept):
        entry = by_concept[concept]
        cid = emitter.node_id(topo_rel, concept)
        concept_ids[concept] = cid
        nodes.append({
            "id": cid,
            "label": f"concept: {concept}",
            "file_type": "code",
            "source_file": topo_rel,
            **blank,
            "dbt_resource_type": "ontology_concept",
            "ontology_id": f"{cfg.topo}{_local(concept)}",
            "ontology_class": cfg.concept_class.get(concept),
            "implemented_by": sorted(entry["implemented_by"]),
            "planned_by": sorted(entry["planned_by"]),
            "supplier_count": len(entry["implemented_by"]),
        })

    for spec in sorted(specs, key=lambda s: s.key):
        ttl_rel = emitter._rel(ontology / "connectors" / f"{spec.key}.ttl")
        gid = emitter.node_id(ttl_rel)
        nodes.append({
            "id": gid,
            "label": f"connector: {spec.name}",
            "file_type": "code",
            "source_file": ttl_rel,
            **blank,
            "dbt_resource_type": "ontology_connector",
            "ontology_id": f"{cfg.connector_ns(spec.key)}connector",
            "connector_key": spec.key,
            "connector_kind": spec.kind,
            "connector_status": spec.status,
            "enable_var": f"is_{spec.key}_enabled",
        })
        # The relation carries the epistemic status, because a flat edge loses it: naive
        # traversal already conflated planned with implemented once ("10 connectors
        # supply Account" — 5 of them were expectations from the catalogue).
        relation = "supplies" if spec.status == "implemented" else "plans_to_supply"
        for concept in (spec.concepts if spec.status == "implemented" else spec.expected_concepts):
            edge(gid, concept_ids[concept], relation)
            model = spec.models.get(concept)
            target = model_gid.get(model) if model else None
            if target:
                edge(target, concept_ids[concept], "implements")

    return {"nodes": nodes, "edges": edges, "hyperedges": [],
            "input_tokens": 0, "output_tokens": 0}


# ---------------------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------------------


def generate(
    slug: str, manifest: Optional[str], use_case: Optional[Path] = None
) -> Dict[str, Any]:
    # A caller that already resolved the directory passes it, rather than having it looked up
    # a second time against this module's own REPO. Two resolutions of one path is one more
    # than can be kept in agreement.
    use_case = use_case or use_case_dir(slug)
    project = use_case / "dbt_project"
    ontology = use_case / "ontology"
    catalogue = ontology / "connectors.yml"
    if not catalogue.exists():
        die(f"no connector catalogue at {catalogue.relative_to(REPO)}")

    cfg = read_config(ontology, slug)
    specs = read_catalogue(catalogue)
    manifest_path = Path(manifest) if manifest else (project / "target/manifest.json")
    problems, lineage_stats = enrich_from_project(specs, project, manifest_path, cfg)

    # Read, never derived: additivity and PII are decisions, so this stage projects the
    # annotations a human wrote and cannot regenerate them. A use-case with none still gets
    # a complete ontology, minus the layer that says what its columns mean.
    annotations = read_annotations(ontology)

    files: Dict[Path, str] = {}
    for spec in specs:
        files[ontology / "connectors" / f"{spec.key}.ttl"] = render_connector(spec, cfg)
    files[ontology / "topology" / "concept-coverage.ttl"] = render_topology(specs, cfg)
    if annotations:
        files[ontology / "topology" / "column-semantics.ttl"] = render_column_semantics(
            annotations, cfg)
    files[ontology / "index.json"] = (
        json.dumps(render_index(specs, cfg, slug, lineage_stats, annotations),
                   indent=2, ensure_ascii=False)
        + "\n"
    )

    unclassified = sorted(
        {
            c
            for s in specs
            for c in (s.concepts if s.status == "implemented" else s.expected_concepts)
            if c not in cfg.concept_class
        }
    )
    return {
        "specs": specs,
        "config": cfg,
        "files": files,
        "problems": problems,
        "unclassified": unclassified,
        "lineage": lineage_stats,
        # The resolved inputs, so a caller building the graphify fragment resolves them
        # zero more times (two resolutions of one path is one more than stays in
        # agreement — same rule as the use_case parameter above).
        "use_case": use_case,
        "manifest_path": manifest_path,
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Generate connector ontologies and topology.")
    p.add_argument("--use-case", default="enhanza-analytics")
    p.add_argument("--manifest", help="manifest.json (default: <project>/target/manifest.json)")
    p.add_argument("--check", action="store_true", help="exit 1 if regeneration would change anything")
    p.add_argument("--force", action="store_true", help="rewrite even when column mappings would be lost")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.add_argument("--graphify-fragment", metavar="PATH",
                   help="write the connector/concept topology as a graphify extraction "
                        "fragment to PATH and exit — the ontology files are not rewritten")
    p.add_argument("--merge-graphify", action="store_true",
                   help="write the fragment and merge it into graphify-out/graph.json "
                        "(never run graphify update after)")
    args = p.parse_args(argv)

    result = generate(args.use_case, args.manifest)
    specs: List[ConnectorSpec] = result["specs"]
    files: Dict[Path, str] = result["files"]

    # A separate mode, not a side effect of generation: the `ontology` stage owns the
    # files, this mode owns the graph. Running it must not rewrite Turtle, and therefore
    # cannot hit the sqlglot downgrade refusal — the fragment carries models, not column
    # mappings, so it is the same with or without the parser.
    if args.graphify_fragment or args.merge_graphify:
        if args.check:
            p.error("--check does not combine with --graphify-fragment/--merge-graphify")
        import dbt_manifest_to_graphify as emitter

        # An implemented connector's topology built without the manifest would assert
        # `implemented_by` on every concept while carrying zero `implements` edges —
        # incomplete carried through as silence, the bug class the column-memory rules
        # name. The dbt emitter makes --manifest required for the same input; a
        # planned-only catalogue has nothing to implement and passes freely.
        manifest_path = result["manifest_path"]
        if any(s.status == "implemented" for s in specs) and not (
            manifest_path and manifest_path.exists()
        ):
            die(
                f"no manifest at {manifest_path} — run artifacts/refresh.sh. An "
                f"implemented connector's topology without it asserts implemented_by "
                f"with no implements edges."
            )

        fragment = build_graphify_fragment(
            specs, result["config"], result["use_case"], manifest_path
        )
        target = (
            Path(args.graphify_fragment)
            if args.graphify_fragment
            else REPO / "graphify-out" / ".graphify_ontology_topology.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(fragment, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        # The same contract as every other mode: problems are printed and fail the run.
        # Here they also refuse the merge — a detector that mutates the graph while
        # staying quiet is the one people read, and a fragment encoding the very drift
        # the problems describe must not become the graph agents orient with.
        if result["problems"]:
            for problem in result["problems"]:
                print(f"  {problem}", file=sys.stderr)
            print(
                f"REFUSED to merge: {len(result['problems'])} problem(s) above. The "
                f"fragment is at {target}; fix the drift and re-run.",
                file=sys.stderr,
            )
        merge_rc = 0
        if args.merge_graphify and not result["problems"]:
            merge_rc = emitter.merge_into_graph(target, result["use_case"] / "dbt_project")
        if args.format == "json":
            print(json.dumps({
                "use_case": args.use_case,
                "fragment": str(target),
                "nodes": len(fragment["nodes"]),
                "edges": len(fragment["edges"]),
                "merged": bool(
                    args.merge_graphify and merge_rc == 0 and not result["problems"]
                ),
                "problems": result["problems"],
            }, ensure_ascii=False))
        else:
            print(f"fragment: {len(fragment['nodes'])} nodes, "
                  f"{len(fragment['edges'])} edges -> {target}")
        return merge_rc or (1 if result["problems"] else 0)

    changed: List[str] = []
    downgrades: List[str] = []
    for path, content in files.items():
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing == content:
            continue
        # Regenerating without sqlglot produces the same classes with none of the column
        # mappings. That is a silent downgrade: the files still look complete, the diff looks
        # like tidying, and 91 verified mappings are gone. Refuse it the way graphify's shrink
        # guard refuses a smaller graph — the fix is to install the parser, not to accept the
        # loss. The marker differs per format; the failure mode does not.
        marker = '"source_column"' if path.suffix == ".json" else "conn:hasMapping"
        if existing and marker in existing and marker not in content:
            downgrades.append(str(path.relative_to(REPO)))
            continue
        changed.append(str(path.relative_to(REPO)))
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    if downgrades and not args.force:
        print(
            f"\nREFUSED to rewrite {len(downgrades)} file(s) that would lose their column\n"
            f"  mappings — {result['lineage'].get('reason', 'column lineage unavailable')}.\n"
            f"  Install sqlglot and re-run, or pass --force to accept the loss.",
            file=sys.stderr,
        )

    impl = [s for s in specs if s.status == "implemented"]
    planned = [s for s in specs if s.status != "implemented"]
    concept_class = result["config"].concept_class
    classes = sum(
        1
        for s in specs
        for c in (s.concepts if s.status == "implemented" else s.expected_concepts)
        if c in concept_class
    )
    mappings = sum(len(v) for s in specs for v in s.mappings.values())

    if args.format == "json":
        print(json.dumps({
            "use_case": args.use_case,
            "connectors": len(specs),
            "implemented": len(impl),
            "planned": len(planned),
            "classes": classes,
            "column_mappings": mappings,
            "lineage_available": result["lineage"].get("available", False),
            "files_written": len(files),
            "files_changed": changed,
            "unclassified_concepts": result["unclassified"],
            "problems": result["problems"],
            "refused_downgrades": downgrades,
        }, ensure_ascii=False))
        return 1 if (args.check and changed) or result["problems"] or (downgrades and not args.force) else 0

    print(f"use-case:   {args.use_case}")
    print(f"connectors: {len(specs)}  ({len(impl)} implemented, {len(planned)} planned)")
    print(f"classes:    {classes} generated across {len(files)} files")
    if result["lineage"].get("available"):
        print(f"mappings:   {mappings} column mappings from parsed SQL")
    else:
        print(f"mappings:   none — {result['lineage'].get('reason', 'lineage unavailable')}")
    if result["unclassified"]:
        print(f"\nunclassified concepts ({len(result['unclassified'])}) — add to CONCEPT_CLASS:")
        for concept in result["unclassified"]:
            print(f"  {concept}")
    if result["problems"]:
        print(f"\nproblems ({len(result['problems'])}):")
        for problem in result["problems"]:
            print(f"  {problem}")
    if downgrades and not args.force:
        return 1
    if args.check:
        if changed:
            print(f"\n{len(changed)} file(s) would change — run without --check:")
            for path in changed[:10]:
                print(f"  {path}")
            return 1
        print("\nGenerated ontology is current.")
    else:
        print(f"\nwrote {len(changed)} changed file(s)")
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
