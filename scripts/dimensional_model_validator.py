#!/usr/bin/env python3
"""Validate a dbt Core project's dimensional model against 15 star-schema rules.

Checks the things `dbt_project_auditor.py` deliberately does not: whether facts join
through conformed dimensions, whether foreign keys are actually tested, whether the SCD2
snapshots are configured recoverably, and whether measures that cannot be summed are
stored as if they can.

    dbt parse
    python scripts/dimensional_model_validator.py --manifest target/manifest.json --strict

--strict exits 1 on any error-severity finding. Never connects to a warehouse — it reads
the manifest, so it can tell you a `relationships` test is missing but not whether that
test would pass.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _manifest import (  # noqa: E402
    Colors,
    Manifest,
    collect_tested_columns,
    header,
    layer_of,
    load_json,
    section,
    severity_tag,
    table,
)

RULES: Dict[str, Tuple[str, str]] = {
    "fact_refs_fact": (
        "error", "Fact references another fact directly instead of joining through a dimension"),
    "fact_fk_untested": (
        "error", "Fact has a foreign key to a dimension with no relationships test"),
    "snapshot_on_model": (
        "error", "Snapshot reads a model instead of a raw source — logic changes rewrite history"),
    "scd2_missing_check_cols": (
        "error", "Snapshot uses the check strategy without check_cols (or timestamp without updated_at)"),
    "fact_without_time_dimension": (
        "warn", "Fact has no date or timestamp column and no date foreign key"),
    "orphan_dimension": (
        "warn", "Dimension is referenced by no fact — a join nobody makes"),
    "nullable_fk_no_unknown_member": (
        "warn", "Foreign key has no not_null test — needs an unknown member row in the dimension"),
    "non_additive_measure_stored": (
        "warn", "Ratio/average stored as a fact column — consumers will sum it"),
    "foreign_entity_measure": (
        "warn", "Measure named for a different entity than the fact's grain — likely double-counted"),
    "denormalized_attribute": (
        "info", "Fact carries a dimension's attribute — needs an as-was vs as-is decision"),
    "conformed_dimension_conflict": (
        "warn", "Two dimensions describe the same entity — they cannot both be conformed"),
    "dimension_not_shared_domain": (
        "warn", "Dimension used by several domains but lives inside one mart domain"),
    "bridge_without_allocation": (
        "warn", "Bridge table has no allocation factor — totals will double-count"),
    "degenerate_dimension_candidate": (
        "info", "Dimension has almost no attributes — it probably belongs on the fact"),
    "unclassified_mart": (
        "info", "Mart model is not named fct_/dim_/bridge_/agg_/rpt_"),
}

FK_SUFFIXES = ("_id", "_sk", "_key", "_fk")
FK_STOPWORDS = {"id", "sk", "key", "primary_key", "surrogate_key", "hash_key"}

NON_ADDITIVE_RE = re.compile(
    r"(^|_)(pct|percent|percentage|rate|ratio|avg|average|mean|median|share|index)($|_)",
    re.IGNORECASE,
)
TIME_COLUMN_RE = re.compile(r"(_at|_date|_day|_month|_week|_year|_ts|_timestamp)$", re.IGNORECASE)
ALLOCATION_RE = re.compile(r"(alloc|weight|factor|share|pct)", re.IGNORECASE)
# Words that mark a column as an aggregate rather than a descriptive attribute. A
# foreign-entity *attribute* is a denormalization choice; a foreign-entity *aggregate* is
# almost always a grain error.
MEASURE_WORD_RE = re.compile(
    r"(^|_)(total|sum|count|num|qty|quantity|amount|balance|level|score|volume|revenue|"
    r"spend|value|size|lifetime|ltv|cumulative|running)($|_)",
    re.IGNORECASE,
)
SHARED_DOMAINS = {"core", "shared", "common", "conformed", "global", "_core"}
TIME_SPINE_RE = re.compile(r"(time_spine|date_spine|dim_date|dim_calendar)", re.IGNORECASE)


class Finding:
    def __init__(self, rule: str, node: str, detail: str, blast: int = 0) -> None:
        self.rule = rule
        self.severity = RULES[rule][0]
        self.node = node
        self.detail = detail
        self.blast = blast

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "node": self.node,
            "detail": self.detail,
            "downstream_count": self.blast,
        }


def classify(name: str) -> str:
    lowered = name.lower()
    if lowered.startswith(("fct_", "fact_")):
        return "fact"
    if lowered.startswith("dim_"):
        return "dimension"
    if lowered.startswith(("bridge_", "br_")):
        return "bridge"
    if lowered.startswith(("agg_", "rpt_")):
        return "aggregate"
    return "other"


def domain_of(node: Dict[str, Any]) -> str:
    """The directory under marts/ — the mart domain, e.g. 'finance'."""
    path = (node.get("path") or node.get("original_file_path") or "").replace("\\", "/")
    parts = [p for p in path.split("/") if p]
    for i, part in enumerate(parts):
        if part.lower() in ("marts", "mart"):
            if i + 1 < len(parts) - 1:
                return parts[i + 1].lower()
            return "_root"
    return parts[-2].lower() if len(parts) >= 2 else "_root"


def dim_entity(name: str) -> str:
    """Normalized entity behind a dimension name: dim_customers -> customer."""
    stem = re.sub(r"^dim_", "", name.lower())
    stem = re.sub(r"_(scd2?|current|history|hist|v\d+)$", "", stem)
    return stem[:-1] if stem.endswith("s") else stem


def column_names(node: Dict[str, Any], catalog_node: Dict[str, Any]) -> List[str]:
    names = list((node.get("columns") or {}).keys())
    lowered = {n.lower() for n in names}
    for col, meta in (catalog_node.get("columns") or {}).items():
        actual = meta.get("name", col)
        if str(actual).lower() not in lowered:
            names.append(str(actual))
    return names


def column_types(catalog_node: Dict[str, Any]) -> Dict[str, str]:
    return {
        str(meta.get("name", col)).lower(): str(meta.get("type", "")).lower()
        for col, meta in (catalog_node.get("columns") or {}).items()
    }


def validate(man: Manifest, catalog: Dict[str, Any],
             only: Optional[List[str]], skip: List[str]) -> List[Finding]:
    findings: List[Finding] = []
    catalog_nodes = (catalog.get("nodes") or {}) if catalog else {}

    def enabled(rule: str) -> bool:
        if only is not None and rule not in only:
            return False
        return rule not in skip

    models = man.models()
    snapshots = man.snapshots()
    tests_by_model = man.tests_by_model()
    child_map = man.child_map()

    marts = {uid: n for uid, n in models.items() if layer_of(n) == "marts"}
    facts = {uid: n for uid, n in marts.items() if classify(n.get("name", "")) == "fact"}
    dims = {uid: n for uid, n in marts.items() if classify(n.get("name", "")) == "dimension"}
    dim_names = {n.get("name") for n in dims.values()}

    # dimension lookup by FK stem: customer_id -> dim_customers
    dim_lookup: Dict[str, str] = {}
    for node in dims.values():
        name = node.get("name", "")
        stem = re.sub(r"^dim_", "", name.lower())
        for variant in (stem, stem.rstrip("s"), stem + "s"):
            dim_lookup.setdefault(variant, name)

    def blast(uid: str) -> int:
        return len(man.descendants(uid))

    # ---- fact-level rules -------------------------------------------------------
    dim_consumers: Dict[str, Set[str]] = {}          # dim name -> domains of facts using it

    # entity prefix -> dimension model, used to spot columns named for another entity
    entity_to_dim: Dict[str, str] = {}
    dim_attributes: Dict[str, Set[str]] = {}
    for duid, dnode in dims.items():
        dname = dnode.get("name", "")
        entity_to_dim.setdefault(dim_entity(dname), dname)
        dim_attributes[dname] = {
            c.lower() for c in column_names(dnode, catalog_nodes.get(duid, {}))
            if not c.lower().endswith(FK_SUFFIXES)
        }

    for uid, node in sorted(facts.items(), key=lambda kv: kv[1].get("name", "")):
        name = node.get("name", "")
        cat = catalog_nodes.get(uid, {})
        cols = column_names(node, cat)
        types = column_types(cat)
        tests = tests_by_model.get(uid, [])
        by_column = collect_tested_columns(tests)
        n_down = blast(uid)

        # fact_refs_fact
        if enabled("fact_refs_fact"):
            for parent in (node.get("depends_on", {}).get("nodes") or []):
                parent_node = models.get(parent)
                if parent_node and classify(parent_node.get("name", "")) == "fact":
                    findings.append(Finding(
                        "fact_refs_fact", name,
                        f"refs {parent_node.get('name')} — facts join through conformed "
                        f"dimensions, never to each other", n_down))

        fact_dims: Set[str] = set()

        # relationships tests present on this fact, by column
        rel_tested: Set[str] = set()
        for test in tests:
            meta = test.get("test_metadata") or {}
            if (meta.get("name") or "").lower() == "relationships":
                col = test.get("column_name") or (meta.get("kwargs") or {}).get("column_name")
                if col:
                    rel_tested.add(str(col).lower())

        for col in cols:
            lowered = col.lower()
            if lowered in FK_STOPWORDS or not lowered.endswith(FK_SUFFIXES):
                continue
            stem = lowered
            for suffix in FK_SUFFIXES:
                if stem.endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            target = dim_lookup.get(stem)
            if not target:
                continue
            dim_consumers.setdefault(target, set()).add(domain_of(node))
            fact_dims.add(target)

            if enabled("fact_fk_untested") and lowered not in rel_tested:
                findings.append(Finding(
                    "fact_fk_untested", name,
                    f"{col} -> {target} has no relationships test; an orphaned fact row "
                    f"would go unnoticed", n_down))

            if enabled("nullable_fk_no_unknown_member"):
                if "not_null" not in by_column.get(col, set()):
                    findings.append(Finding(
                        "nullable_fk_no_unknown_member", name,
                        f"{col} is nullable — add not_null, or an unknown member row in "
                        f"{target} and coalesce to it", n_down))

        # fact_without_time_dimension
        if enabled("fact_without_time_dimension"):
            has_time = any(
                TIME_COLUMN_RE.search(c) or
                any(t in types.get(c.lower(), "") for t in ("date", "time"))
                for c in cols
            )
            if cols and not has_time:
                findings.append(Finding(
                    "fact_without_time_dimension", name,
                    "no date/timestamp column found — a fact with no time cannot be "
                    "trended or partitioned", n_down))

        # non_additive_measure_stored
        if enabled("non_additive_measure_stored"):
            for col in cols:
                if col.lower().endswith(FK_SUFFIXES):
                    continue
                if NON_ADDITIVE_RE.search(col):
                    findings.append(Finding(
                        "non_additive_measure_stored", name,
                        f"{col} cannot be summed; store numerator and denominator and "
                        f"define the ratio as a metric", n_down))

        # Mixed-grain suspects. A fact's own entity is in its name (fct_orders -> order);
        # a column named for a *different* entity is either a denormalized attribute (a
        # choice) or an aggregate at that entity's grain (a defect).
        own_entity = re.sub(r"^(fct|fact)_", "", name.lower())
        own_entity = own_entity[:-1] if own_entity.endswith("s") else own_entity

        for col in cols:
            lowered = col.lower()
            if lowered.endswith(FK_SUFFIXES):
                continue
            prefix = lowered.split("_")[0]
            foreign = entity_to_dim.get(prefix) or entity_to_dim.get(prefix.rstrip("s"))

            if (enabled("foreign_entity_measure") and foreign and prefix != own_entity
                    and MEASURE_WORD_RE.search(lowered)):
                findings.append(Finding(
                    "foreign_entity_measure", name,
                    f"{col} is an aggregate at {foreign}'s grain, not this fact's — it is "
                    f"summed once per fact row and the total is meaningless", n_down))
                continue

            if enabled("denormalized_attribute"):
                for dim_name in sorted(fact_dims):
                    if lowered in dim_attributes.get(dim_name, set()):
                        findings.append(Finding(
                            "denormalized_attribute", name,
                            f"{col} also exists on {dim_name} — record whether it is the "
                            f"value as-was (at event time) or as-is (current)", n_down))
                        break

    # ---- dimension-level rules --------------------------------------------------
    for uid, node in sorted(dims.items(), key=lambda kv: kv[1].get("name", "")):
        name = node.get("name", "")
        cols = column_names(node, catalog_nodes.get(uid, {}))
        n_down = blast(uid)

        if enabled("orphan_dimension") and not TIME_SPINE_RE.search(name):
            # Two independent signals: a ref() edge from a fact/bridge, or a fact column
            # whose name resolves to this dimension. Either one means it is in use.
            consumed_by_fact = any(
                models.get(child) and classify(models[child].get("name", "")) in ("fact", "bridge")
                for child in child_map.get(uid, [])
            ) or name in dim_consumers
            if not consumed_by_fact:
                findings.append(Finding(
                    "orphan_dimension", name,
                    "no fact or bridge references it — either a fact is missing its FK "
                    "test/column, or nobody slices by this", n_down))

        if enabled("degenerate_dimension_candidate") and 0 < len(cols) <= 2:
            findings.append(Finding(
                "degenerate_dimension_candidate", name,
                f"only {len(cols)} column(s) — an identifier with no attributes is a "
                f"degenerate dimension and belongs on the fact", n_down))

        if enabled("dimension_not_shared_domain"):
            domains = dim_consumers.get(name, set())
            own_domain = domain_of(node)
            if len(domains) > 1 and own_domain not in SHARED_DOMAINS:
                findings.append(Finding(
                    "dimension_not_shared_domain", name,
                    f"used by domains {sorted(domains)} but lives in '{own_domain}' — "
                    f"move it to a shared core domain before it gets copied", n_down))

    # conformed_dimension_conflict
    if enabled("conformed_dimension_conflict"):
        by_entity: Dict[str, List[str]] = {}
        for node in dims.values():
            by_entity.setdefault(dim_entity(node.get("name", "")), []).append(
                node.get("name", ""))
        for entity, names in sorted(by_entity.items()):
            if len(names) > 1:
                findings.append(Finding(
                    "conformed_dimension_conflict", ", ".join(sorted(names)),
                    f"both describe '{entity}' — two definitions means the stars using "
                    f"them can never be compared", 0))

    # ---- bridge rules -----------------------------------------------------------
    if enabled("bridge_without_allocation"):
        for uid, node in sorted(marts.items(), key=lambda kv: kv[1].get("name", "")):
            name = node.get("name", "")
            if classify(name) != "bridge":
                continue
            cols = column_names(node, catalog_nodes.get(uid, {}))
            if cols and not any(ALLOCATION_RE.search(c) for c in cols):
                findings.append(Finding(
                    "bridge_without_allocation", name,
                    "no allocation/weight column — summing a measure across this bridge "
                    "counts each parent once per child", blast(uid)))

    # ---- unclassified marts -----------------------------------------------------
    if enabled("unclassified_mart"):
        for uid, node in sorted(marts.items(), key=lambda kv: kv[1].get("name", "")):
            name = node.get("name", "")
            if classify(name) == "other" and not TIME_SPINE_RE.search(name):
                findings.append(Finding(
                    "unclassified_mart", name,
                    "a mart's kind should be readable from its name", blast(uid)))

    # ---- snapshot rules ---------------------------------------------------------
    for uid, node in sorted(snapshots.items(), key=lambda kv: kv[1].get("name", "")):
        name = node.get("name", "")
        config = node.get("config") or {}
        n_down = blast(uid)

        if enabled("snapshot_on_model"):
            model_parents = [
                models[p].get("name") for p in (node.get("depends_on", {}).get("nodes") or [])
                if p in models
            ]
            if model_parents:
                findings.append(Finding(
                    "snapshot_on_model", name,
                    f"reads model(s) {', '.join(str(m) for m in model_parents)} — snapshot "
                    f"the raw source, or a logic change silently rewrites history", n_down))

        if enabled("scd2_missing_check_cols"):
            strategy = str(config.get("strategy") or "").lower()
            if strategy == "check":
                check_cols = config.get("check_cols")
                if not check_cols:
                    findings.append(Finding(
                        "scd2_missing_check_cols", name,
                        "strategy: check with no check_cols — set the columns, or 'all'",
                        n_down))
            elif strategy == "timestamp" and not config.get("updated_at"):
                findings.append(Finding(
                    "scd2_missing_check_cols", name,
                    "strategy: timestamp with no updated_at column", n_down))
            elif not strategy:
                findings.append(Finding(
                    "scd2_missing_check_cols", name,
                    "no snapshot strategy declared", n_down))

    order = {"error": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: (order[f.severity], -f.blast, f.rule, f.node))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validate a dbt project's dimensional model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--manifest", default="target/manifest.json")
    ap.add_argument("--catalog", help="target/catalog.json, for columns dbt does not declare")
    ap.add_argument("--only", help="comma-separated rule ids to run exclusively")
    ap.add_argument("--skip", default="", help="comma-separated rule ids to skip")
    ap.add_argument("--strict", action="store_true", help="exit 1 on any error finding")
    ap.add_argument("--max-per-rule", type=int, default=15)
    ap.add_argument("--json", dest="json_out", help="write findings to a JSON file")
    ap.add_argument("--list-rules", action="store_true")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()

    if args.no_color or not sys.stdout.isatty():
        Colors.disable()

    if args.list_rules:
        header("Dimensional model rules")
        table([[rule, sev, desc] for rule, (sev, desc) in RULES.items()],
              ["rule", "severity", "description"], max_width=70)
        return 0

    only = [r.strip() for r in args.only.split(",")] if args.only else None
    skip = [r.strip() for r in args.skip.split(",") if r.strip()]
    for rule in (only or []) + skip:
        if rule not in RULES:
            print(f"ERROR: unknown rule '{rule}'. Use --list-rules.", file=sys.stderr)
            return 2

    man = Manifest.load(args.manifest)
    catalog = load_json(args.catalog, "catalog") if args.catalog else {}
    findings = validate(man, catalog, only, skip)

    marts = [n for n in man.models().values() if layer_of(n) == "marts"]
    kinds: Dict[str, int] = {}
    for node in marts:
        kind = classify(node.get("name", ""))
        kinds[kind] = kinds.get(kind, 0) + 1

    header(f"Dimensional Model — {man.project_name}")
    print("  " + " · ".join(f"{count} {kind}" for kind, count in sorted(kinds.items()))
          + f" · {len(man.snapshots())} snapshot(s)")

    counts = {"error": 0, "warn": 0, "info": 0}
    for finding in findings:
        counts[finding.severity] += 1

    if not findings:
        print(f"\n{Colors.GREEN}Clean — no dimensional findings.{Colors.END}")
    else:
        by_rule: Dict[str, List[Finding]] = {}
        for finding in findings:
            by_rule.setdefault(finding.rule, []).append(finding)
        for rule, group in by_rule.items():
            sev, desc = RULES[rule]
            section(f"[{sev.upper()}] {rule} — {desc}  ({len(group)})")
            table([[f.node, str(f.blast) if f.blast else "-", f.detail]
                   for f in group[: args.max_per_rule]],
                  ["node", "downstream", "detail"], max_width=78)
            if len(group) > args.max_per_rule:
                print(f"  ... and {len(group) - args.max_per_rule} more")

    section("Summary")
    print(f"  {severity_tag('error')}  {counts['error']}")
    print(f"  {severity_tag('warn')}  {counts['warn']}")
    print(f"  {severity_tag('info')}  {counts['info']}")
    print("\n  This checks the shape of the star, not the numbers in it. Mixed-grain")
    print("  detection is name-based: it flags a measure named for another entity, and")
    print("  cannot see one that is named neutrally. A grain error with a plausible column")
    print("  name has the same manifest signature as a correct model — that stays human")
    print("  review, and a fan-out unit test is what actually proves it.")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"project": man.project_name, "counts": counts,
                       "findings": [f.as_dict() for f in findings]}, fh, indent=2)
        print(f"\n  Wrote {args.json_out}")

    if args.strict and counts["error"]:
        print(f"\n{Colors.RED}--strict: {counts['error']} error-severity finding(s).{Colors.END}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
