#!/usr/bin/env python3
"""Audit a dbt Core project against 20 structural health rules.

Reads target/manifest.json (and optionally the project files) and reports findings
ranked by severity and by how many nodes depend on the offending model. Never connects
to a warehouse.

    dbt parse
    python scripts/dbt_project_auditor.py --manifest target/manifest.json --strict

--strict exits 1 on any error-severity finding, which is how you gate a PR.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _manifest import (  # noqa: E402
    Colors,
    Manifest,
    has_primary_key_tests,
    header,
    layer_of,
    section,
    severity_tag,
    table,
    tested_columns,
)

# Rule id -> (severity, one-line description)
RULES: Dict[str, tuple] = {
    "missing_pk_test": ("error", "Model has no unique+not_null (or composite grain) test"),
    "no_tests": ("error", "Model has no tests at all"),
    "hardcoded_ref": ("error", "SQL references a table directly instead of ref()/source()"),
    "source_without_freshness": ("error", "Source has no freshness block and no explicit null"),
    "source_without_loaded_at": ("error", "Source declares freshness but no loaded_at_field"),
    "dag_cycle": ("error", "Dependency cycle in the DAG"),
    "contract_missing_types": ("error", "Contracted model has columns without data_type"),
    "undocumented_model": ("warn", "Model has no description"),
    "description_restates_name": ("warn", "Description just restates the model name"),
    "mart_undocumented_columns": ("warn", "Mart column has no description"),
    "select_star_in_mart": ("warn", "Mart's final projection uses select *"),
    "orphan_model": ("warn", "Mart has no downstream model and no exposure"),
    "layer_violation": ("warn", "Model references across a layer boundary incorrectly"),
    "mart_refs_source": ("warn", "Mart or intermediate model references a source directly"),
    "staging_has_join": ("warn", "Staging model contains a join or aggregation"),
    "incremental_no_unique_key": ("warn", "Incremental model with merge/delete+insert has no unique_key"),
    "incremental_schema_change_default": ("warn", "Incremental model leaves on_schema_change at ignore"),
    "logic_without_unit_test": ("warn", "Model has real logic but no unit test"),
    "public_without_contract": ("warn", "access: public without contract: enforced"),
    "naming_convention": ("info", "Model name does not match its layer's convention"),
}

# Table-ish identifiers that are almost certainly hardcoded refs.
HARDCODED = re.compile(
    r"\b(from|join)\s+(?!\()"                      # from/join, not a subquery
    r"(?!\{\{)"                                    # not a Jinja expression
    r"([a-zA-Z_][\w]*\.[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*)?)",
    re.IGNORECASE,
)
JOIN_RE = re.compile(r"\bjoin\b", re.IGNORECASE)
AGG_RE = re.compile(r"\b(group\s+by|sum\s*\(|count\s*\(|avg\s*\(|max\s*\(|min\s*\()", re.IGNORECASE)
LOGIC_RE = re.compile(
    r"(\bcase\s+when\b|\bover\s*\(|\bregexp|\brlike\b|\bdate(add|diff|_trunc)\b|"
    r"\blag\s*\(|\blead\s*\(|\brow_number\s*\(|\bcoalesce\s*\([^)]*,[^)]*,)",
    re.IGNORECASE,
)


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


def strip_sql(sql: str) -> str:
    """Remove comments and Jinja blocks so regex checks see only SQL."""
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"\{\{.*?\}\}", " __JINJA__ ", sql, flags=re.DOTALL)
    sql = re.sub(r"\{%.*?%\}", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"\{#.*?#\}", " ", sql, flags=re.DOTALL)
    return sql


def final_projection(sql: str) -> str:
    """The last top-level select — where `select *` actually matters."""
    cleaned = strip_sql(sql)
    idx = cleaned.lower().rfind("select")
    return cleaned[idx:] if idx >= 0 else cleaned


def audit(man: Manifest, only: Optional[List[str]], skip: List[str]) -> List[Finding]:
    findings: List[Finding] = []
    models = man.models()
    tests_by_model = man.tests_by_model()
    child_map = man.child_map()

    def enabled(rule: str) -> bool:
        if rule in skip:
            return False
        return not only or rule in only

    def blast(uid: str) -> int:
        return len(man.descendants(uid))

    # --- DAG-level ------------------------------------------------
    if enabled("dag_cycle"):
        for cycle in man.find_cycles():
            names = " -> ".join(man.nodes.get(u, {}).get("name", u) for u in cycle)
            findings.append(Finding("dag_cycle", cycle[0], names))

    # --- sources --------------------------------------------------
    for uid, src in man.sources.items():
        label = f"{src.get('source_name')}.{src.get('name')}"
        freshness = src.get("freshness")
        has_window = bool(freshness) and (
            freshness.get("warn_after", {}).get("count") is not None
            or freshness.get("error_after", {}).get("count") is not None
        )
        # dbt represents an explicit `freshness: null` as an all-null block, which is a
        # deliberate opt-out, versus a source that simply never mentioned freshness.
        declared = "freshness" in (src.get("unrendered_config") or {}) or freshness is not None
        if enabled("source_without_freshness") and not has_window and not declared:
            findings.append(
                Finding("source_without_freshness", label,
                        "no freshness block — set warn_after/error_after, or `freshness: null` to opt out")
            )
        if enabled("source_without_loaded_at") and has_window and not src.get("loaded_at_field"):
            findings.append(
                Finding("source_without_loaded_at", label,
                        "freshness declared but loaded_at_field is missing")
            )

    # --- models ---------------------------------------------------
    for uid, model in models.items():
        name = model.get("name", uid)
        cfg = model.get("config", {}) or {}
        layer = layer_of(model)
        raw = model.get("raw_code") or model.get("raw_sql") or ""
        sql = strip_sql(raw)
        tests = tests_by_model.get(uid, [])
        test_kinds = {
            (t.get("test_metadata") or {}).get("name") or t.get("resource_type")
            for t in tests
        }
        n_down = blast(uid)

        if enabled("no_tests") and not tests:
            findings.append(Finding("no_tests", name, "no tests attached", n_down))
        elif enabled("missing_pk_test") and not has_primary_key_tests(tests):
            cols = tested_columns(tests)
            detail = (
                "tested columns: " + ", ".join(sorted(cols)) if cols else "no column tests"
            )
            findings.append(
                Finding("missing_pk_test", name,
                        f"no column has both unique and not_null ({detail})", n_down)
            )

        description = (model.get("description") or "").strip()
        if enabled("undocumented_model") and not description:
            findings.append(Finding("undocumented_model", name, "description is empty", n_down))
        elif enabled("description_restates_name") and description:
            normalized = re.sub(r"[^a-z0-9]", "", description.lower())
            bare = re.sub(r"[^a-z0-9]", "", name.lower())
            if normalized in (bare, bare + "table", bare + "model") or len(description) < 15:
                findings.append(
                    Finding("description_restates_name", name,
                            f"description is {description!r} — state the grain instead", n_down)
                )

        if enabled("hardcoded_ref"):
            for match in HARDCODED.finditer(sql):
                ident = match.group(2)
                if ident.lower().startswith(("information_schema", "unnest", "lateral")):
                    continue
                findings.append(
                    Finding("hardcoded_ref", name,
                            f"`{match.group(1)} {ident}` — use ref() or source()", n_down)
                )
                break  # one finding per model is enough to act on

        if enabled("select_star_in_mart") and layer == "marts":
            projection = final_projection(raw)
            # `select * from final` is the sanctioned idiom; anything else is a real star.
            if re.search(r"select\s+\*", projection, re.IGNORECASE) and not re.search(
                r"select\s+\*\s+from\s+\w+\s*$", projection.strip(), re.IGNORECASE
            ):
                findings.append(
                    Finding("select_star_in_mart", name,
                            "final projection selects * — enumerate columns", n_down)
                )

        if enabled("orphan_model") and layer == "marts" and n_down == 0:
            findings.append(
                Finding("orphan_model", name,
                        "no downstream model and no exposure — name a consumer or delete it")
            )

        parents = model.get("depends_on", {}).get("nodes", []) or []
        if enabled("mart_refs_source") and layer in ("marts", "intermediate"):
            src_parents = [p for p in parents if p.startswith("source.")]
            if src_parents:
                findings.append(
                    Finding("mart_refs_source", name,
                            f"references source(s) directly: {', '.join(src_parents[:3])} — "
                            f"go through a staging model", n_down)
                )

        if enabled("layer_violation"):
            for parent in parents:
                pnode = man.nodes.get(parent)
                if not pnode:
                    continue
                player = layer_of(pnode)
                if layer == "staging" and player in ("intermediate", "marts"):
                    findings.append(
                        Finding("layer_violation", name,
                                f"staging model references {player} model "
                                f"{pnode.get('name')}", n_down)
                    )
                elif layer == "marts" and player == "marts" and pnode.get("name", "").startswith("int_"):
                    findings.append(
                        Finding("layer_violation", name,
                                f"mart references another mart's internals "
                                f"({pnode.get('name')}) — extract to intermediate", n_down)
                    )

        if enabled("staging_has_join") and layer == "staging":
            if JOIN_RE.search(sql) or AGG_RE.search(sql):
                what = "join" if JOIN_RE.search(sql) else "aggregation"
                findings.append(
                    Finding("staging_has_join", name,
                            f"staging model contains a {what} — move it to intermediate", n_down)
                )

        materialized = cfg.get("materialized")
        if materialized == "incremental":
            strategy = cfg.get("incremental_strategy") or "merge"
            if enabled("incremental_no_unique_key") and strategy in ("merge", "delete+insert"):
                if not cfg.get("unique_key"):
                    findings.append(
                        Finding("incremental_no_unique_key", name,
                                f"incremental_strategy={strategy} requires unique_key — "
                                f"without it rows duplicate", n_down)
                    )
            if enabled("incremental_schema_change_default"):
                if (cfg.get("on_schema_change") or "ignore") == "ignore":
                    findings.append(
                        Finding("incremental_schema_change_default", name,
                                "on_schema_change is 'ignore' — new upstream columns are "
                                "silently dropped. Set append_new_columns", n_down)
                    )

        if enabled("logic_without_unit_test") and LOGIC_RE.search(sql):
            if "unit_test" not in test_kinds:
                findings.append(
                    Finding("logic_without_unit_test", name,
                            "contains CASE/window/regex/date-math but has no unit test", n_down)
                )

        contract = cfg.get("contract") or {}
        if enabled("contract_missing_types") and contract.get("enforced"):
            missing = [
                c for c, meta in (model.get("columns") or {}).items()
                if not (meta or {}).get("data_type")
            ]
            if missing:
                findings.append(
                    Finding("contract_missing_types", name,
                            f"contract enforced but {len(missing)} column(s) lack data_type: "
                            f"{', '.join(missing[:5])}", n_down)
                )

        if enabled("public_without_contract") and cfg.get("access") == "public":
            if not contract.get("enforced"):
                findings.append(
                    Finding("public_without_contract", name,
                            "access: public without an enforced contract — the promise is "
                            "unenforced", n_down)
                )

        if enabled("mart_undocumented_columns") and layer == "marts":
            undoc = [
                c for c, meta in (model.get("columns") or {}).items()
                if not (meta or {}).get("description", "").strip()
            ]
            if undoc:
                findings.append(
                    Finding("mart_undocumented_columns", name,
                            f"{len(undoc)} column(s) undocumented: "
                            f"{', '.join(undoc[:5])}", n_down)
                )

        if enabled("naming_convention"):
            expected = {
                "staging": ("stg_",),
                "intermediate": ("int_",),
                "marts": ("fct_", "dim_", "rpt_", "agg_", "bridge_"),
            }.get(layer)
            if expected and not name.startswith(expected):
                findings.append(
                    Finding("naming_convention", name,
                            f"in {layer}/ but does not start with "
                            f"{' or '.join(expected)}", n_down)
                )

    order = {"error": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: (order[f.severity], -f.blast, f.rule, f.node))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Audit a dbt Core project against 20 structural health rules.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Rules:\n"
        + "\n".join(f"  {r:36s} [{s}] {d}" for r, (s, d) in RULES.items()),
    )
    ap.add_argument("--manifest", default="target/manifest.json")
    ap.add_argument("--project-dir", default=".", help="reserved for file-level checks")
    ap.add_argument("--only", help="comma-separated rule ids to run exclusively")
    ap.add_argument("--skip", default="", help="comma-separated rule ids to skip")
    ap.add_argument("--strict", action="store_true", help="exit 1 on any error finding")
    ap.add_argument("--max-per-rule", type=int, default=15)
    ap.add_argument("--json", dest="json_out", help="write findings to a JSON file")
    ap.add_argument("--list-rules", action="store_true")
    args = ap.parse_args()

    if args.list_rules:
        for rule, (sev, desc) in RULES.items():
            print(f"{rule:36s} [{sev:5s}] {desc}")
        return 0

    only = [r.strip() for r in args.only.split(",")] if args.only else None
    skip = [r.strip() for r in args.skip.split(",") if r.strip()]
    for rule in (only or []) + skip:
        if rule not in RULES:
            print(f"ERROR: unknown rule '{rule}'. Use --list-rules.", file=sys.stderr)
            return 2

    man = Manifest.load(args.manifest)
    findings = audit(man, only, skip)

    header(f"dbt Project Audit — {man.project_name}")
    print(f"dbt {man.dbt_version} · adapter {man.adapter_type} · "
          f"{len(man.models())} models · {len(man.sources)} sources · "
          f"{len(man.tests())} tests · {len(man.exposures)} exposures")

    counts = {"error": 0, "warn": 0, "info": 0}
    for finding in findings:
        counts[finding.severity] += 1

    if not findings:
        print(f"\n{Colors.GREEN}Clean — no findings.{Colors.END}")
    else:
        by_rule: Dict[str, List[Finding]] = {}
        for finding in findings:
            by_rule.setdefault(finding.rule, []).append(finding)
        for rule, group in by_rule.items():
            sev, desc = RULES[rule]
            section(f"[{sev.upper()}] {rule} — {desc}  ({len(group)})")
            rows = [
                [f.node, str(f.blast) if f.blast else "-", f.detail]
                for f in group[: args.max_per_rule]
            ]
            table(rows, ["node", "downstream", "detail"], max_width=78)
            if len(group) > args.max_per_rule:
                print(f"  ... and {len(group) - args.max_per_rule} more")

    section("Summary")
    print(f"  {severity_tag('error')}  {counts['error']}")
    print(f"  {severity_tag('warn')}  {counts['warn']}")
    print(f"  {severity_tag('info')}  {counts['info']}")
    print("\n  Findings are ordered by severity, then by how many nodes depend on the")
    print("  offending model. Fix from the top — blast radius is what makes a gap matter.")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "project": man.project_name,
                    "dbt_version": man.dbt_version,
                    "counts": counts,
                    "findings": [f.as_dict() for f in findings],
                },
                fh,
                indent=2,
            )
        print(f"\n  Wrote {args.json_out}")

    if args.strict and counts["error"]:
        print(f"\n{Colors.RED}--strict: {counts['error']} error-severity finding(s).{Colors.END}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
