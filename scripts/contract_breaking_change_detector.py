#!/usr/bin/env python3
"""Detect breaking changes between two dbt Core manifests.

Run in CI against the production manifest. Catches removed models and columns, data-type
changes on contracted models, contracts disabled, access narrowed, version changes, and
public models losing their contract.

    python scripts/contract_breaking_change_detector.py \
        --base prod/manifest.json --head target/manifest.json --strict

What it CANNOT catch: a grain change. The column list is identical, every contract
passes, every test passes, and every downstream number is silently wrong. The report
says so and lists the models whose SQL changed so a human can check.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _manifest import (  # noqa: E402
    Colors,
    Manifest,
    header,
    section,
    table,
)

ACCESS_RANK = {"public": 2, "protected": 1, "private": 0}


class Change:
    def __init__(self, severity: str, kind: str, model: str, detail: str,
                 impact: int = 0, consumers: Optional[List[str]] = None) -> None:
        self.severity = severity      # breaking | risky | info
        self.kind = kind
        self.model = model
        self.detail = detail
        self.impact = impact
        self.consumers = consumers or []

    def as_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "kind": self.kind,
            "model": self.model,
            "detail": self.detail,
            "downstream_nodes": self.impact,
            "exposures": self.consumers,
        }


def normalize_type(dtype: Optional[str]) -> str:
    """Compare types loosely enough to avoid noise, strictly enough to catch real breaks."""
    if not dtype:
        return ""
    return "".join(str(dtype).lower().split())


def detect(base: Manifest, head: Manifest) -> List[Change]:
    changes: List[Change] = []
    base_models = base.models()
    head_models = head.models()

    def impact_of(uid: str) -> tuple:
        if uid not in head.all_nodes() and uid not in head.nodes:
            return 0, []
        down = head.descendants(uid)
        exposures = [
            head.exposures.get(d, {}).get("name", d)
            for d in down
            if d.startswith("exposure.")
        ]
        return len(down), sorted(exposures)

    # ---- removed models
    for uid, model in base_models.items():
        if uid in head_models:
            continue
        old_impact = len(base.descendants(uid))
        cfg = model.get("config", {}) or {}
        severity = "breaking" if cfg.get("access") == "public" or old_impact else "risky"
        changes.append(Change(
            severity, "model_removed", model.get("name", uid),
            f"model no longer exists (had {old_impact} downstream node(s) in base)",
            old_impact,
        ))

    # ---- per-model comparison
    for uid, new in head_models.items():
        old = base_models.get(uid)
        name = new.get("name", uid)
        if old is None:
            continue  # new models are never breaking

        new_cfg = new.get("config", {}) or {}
        old_cfg = old.get("config", {}) or {}
        new_contract = (new_cfg.get("contract") or {}).get("enforced", False)
        old_contract = (old_cfg.get("contract") or {}).get("enforced", False)
        impact, exposures = impact_of(uid)

        new_cols = new.get("columns") or {}
        old_cols = old.get("columns") or {}

        # Columns removed. Only meaningful when the model documents its columns —
        # an undocumented model has no declared surface to break.
        if old_cols:
            removed = [c for c in old_cols if c not in new_cols]
            if removed:
                sev = "breaking" if old_contract or exposures else "risky"
                changes.append(Change(
                    sev, "column_removed", name,
                    f"column(s) removed: {', '.join(sorted(removed)[:6])}"
                    + (f" (+{len(removed)-6} more)" if len(removed) > 6 else ""),
                    impact, exposures,
                ))

            # Type changes
            for col, meta in new_cols.items():
                old_meta = old_cols.get(col)
                if not old_meta:
                    continue
                old_type = normalize_type((old_meta or {}).get("data_type"))
                new_type = normalize_type((meta or {}).get("data_type"))
                if old_type and new_type and old_type != new_type:
                    sev = "breaking" if old_contract else "risky"
                    changes.append(Change(
                        sev, "data_type_changed", name,
                        f"{col}: {old_meta.get('data_type')} -> {meta.get('data_type')}",
                        impact, exposures,
                    ))

        # Contract turned off
        if old_contract and not new_contract:
            changes.append(Change(
                "breaking", "contract_removed", name,
                "contract enforcement removed — the guarantee is withdrawn",
                impact, exposures,
            ))
        elif new_contract and not old_contract:
            changes.append(Change("info", "contract_added", name,
                                  "contract now enforced", impact, exposures))

        # Access narrowed
        old_access = old_cfg.get("access", "protected")
        new_access = new_cfg.get("access", "protected")
        if ACCESS_RANK.get(new_access, 1) < ACCESS_RANK.get(old_access, 1):
            changes.append(Change(
                "breaking", "access_narrowed", name,
                f"access {old_access} -> {new_access}; existing consumers may lose the ref",
                impact, exposures,
            ))

        # Versions
        old_latest = old.get("latest_version")
        new_latest = new.get("latest_version")
        if old_latest != new_latest and (old_latest or new_latest):
            changes.append(Change(
                "risky", "latest_version_changed", name,
                f"latest_version {old_latest} -> {new_latest}; "
                f"unpinned ref() consumers move automatically",
                impact, exposures,
            ))

        # Materialization
        old_mat = old_cfg.get("materialized")
        new_mat = new_cfg.get("materialized")
        if old_mat != new_mat:
            sev = "risky" if new_mat in ("ephemeral", "view") and old_mat == "table" else "info"
            changes.append(Change(
                sev, "materialization_changed", name,
                f"materialized {old_mat} -> {new_mat}", impact, exposures,
            ))

        # Relation identity — the table consumers query by name
        for key in ("database", "schema", "alias"):
            if old.get(key) != new.get(key) and (old.get(key) or new.get(key)):
                changes.append(Change(
                    "breaking", "relation_moved", name,
                    f"{key}: {old.get(key)} -> {new.get(key)}; "
                    f"anything selecting by physical name breaks",
                    impact, exposures,
                ))

        # Public with no contract
        if new_access == "public" and not new_contract:
            changes.append(Change(
                "risky", "public_without_contract", name,
                "access: public with no enforced contract", impact, exposures,
            ))

    # ---- removed sources and exposures
    for uid, src in base.sources.items():
        if uid not in head.sources:
            changes.append(Change(
                "risky", "source_removed",
                f"{src.get('source_name')}.{src.get('name')}",
                "source definition removed",
            ))
    for uid, exp in base.exposures.items():
        if uid not in head.exposures:
            changes.append(Change("info", "exposure_removed", exp.get("name", uid),
                                  "exposure removed from the project"))

    order = {"breaking": 0, "risky": 1, "info": 2}
    changes.sort(key=lambda c: (order[c.severity], -len(c.consumers), -c.impact, c.model))
    return changes


def sql_changed_models(base: Manifest, head: Manifest) -> List[str]:
    out = []
    base_models = base.models()
    for uid, new in head.models().items():
        old = base_models.get(uid)
        if old is None:
            continue
        if (new.get("raw_code") or new.get("raw_sql")) != (
            old.get("raw_code") or old.get("raw_sql")
        ):
            out.append(new.get("name", uid))
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Detect breaking changes between two dbt manifests."
    )
    ap.add_argument("--base", required=True, help="the production manifest.json")
    ap.add_argument("--head", default="target/manifest.json", help="this branch's manifest")
    ap.add_argument("--strict", action="store_true", help="exit 1 on any breaking change")
    ap.add_argument("--fail-on-risky", action="store_true")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()

    base = Manifest.load(args.base)
    head = Manifest.load(args.head)

    header("Breaking change detection")
    print(f"  base: {args.base}  (dbt {base.dbt_version}, {len(base.models())} models)")
    print(f"  head: {args.head}  (dbt {head.dbt_version}, {len(head.models())} models)")
    if base.dbt_version != head.dbt_version:
        print(f"\n  {Colors.YELLOW}dbt versions differ between manifests. Some diffs below")
        print(f"  may be schema changes in dbt itself rather than in your project.{Colors.END}")
    if base.project_name != head.project_name:
        print(f"\n  {Colors.RED}Different project names ({base.project_name} vs "
              f"{head.project_name}). This comparison is probably meaningless.{Colors.END}")

    changes = detect(base, head)
    counts = {"breaking": 0, "risky": 0, "info": 0}
    for c in changes:
        counts[c.severity] += 1

    for severity, colour in (("breaking", Colors.RED), ("risky", Colors.YELLOW),
                             ("info", Colors.BLUE)):
        group = [c for c in changes if c.severity == severity]
        if not group:
            continue
        section(f"{colour}{severity.upper()}{Colors.END} ({len(group)})")
        table(
            [[c.model, c.kind, c.detail, str(c.impact) if c.impact else "-",
              ", ".join(c.consumers[:2]) or "-"] for c in group],
            ["model", "kind", "detail", "downstream", "exposures"],
            max_width=40,
        )

    if not changes:
        print(f"\n  {Colors.GREEN}No contract-visible changes.{Colors.END}")

    # ---- the class this tool cannot detect
    sql_changed = sql_changed_models(base, head)
    if sql_changed:
        section("Needs human review — SQL changed, shape did not")
        print("  A GRAIN CHANGE is invisible here: the column list is identical, every")
        print("  contract passes, every test passes, and every downstream number is")
        print("  silently wrong. For each model below, confirm the grain sentence in its")
        print("  description still holds.\n")
        table([[m] for m in sql_changed[:25]], ["model with changed SQL"])
        if len(sql_changed) > 25:
            print(f"  ... and {len(sql_changed) - 25} more")

    section("What to do")
    if counts["breaking"]:
        print("  Breaking changes need one of:")
        print("    1. A model version with a deprecation_date (preferred for public models)")
        print("    2. Every consumer updated in the same PR")
        print("    3. An explicit, announced coordination window")
    else:
        print("  No breaking changes. Additive changes ship freely — but update the")
        print("  contract YAML in the same PR for any contracted model.")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "base": args.base,
                    "head": args.head,
                    "counts": counts,
                    "changes": [c.as_dict() for c in changes],
                    "sql_changed_needs_grain_review": sql_changed,
                },
                fh,
                indent=2,
            )
        print(f"\n  Wrote {args.json_out}")

    if args.strict and counts["breaking"]:
        print(f"\n{Colors.RED}--strict: {counts['breaking']} breaking change(s).{Colors.END}")
        return 1
    if args.fail_on_risky and (counts["breaking"] or counts["risky"]):
        print(f"\n{Colors.RED}--fail-on-risky: "
              f"{counts['breaking'] + counts['risky']} change(s).{Colors.END}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
