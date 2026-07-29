#!/usr/bin/env python3
"""Analyze a dbt Core DAG: lineage, blast radius, fan-in/out, cycles, layer violations,
and Mermaid diagrams.

    dbt parse
    python scripts/model_dependency_analyzer.py --manifest target/manifest.json \
        --model fct_orders --direction down
    python scripts/model_dependency_analyzer.py --manifest target/manifest.json --mermaid
    python scripts/model_dependency_analyzer.py --manifest target/manifest.json \
        --changed-vs prod/manifest.json --mermaid

Run this BEFORE changing a model. Blast radius is the difference between a safe edit
and an incident.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _manifest import (  # noqa: E402
    Colors,
    Manifest,
    header,
    layer_of,
    section,
    table,
)

LAYER_ORDER = {"staging": 1, "intermediate": 2, "marts": 3, "semantic": 4, "other": 0}
MERMAID_STYLE = {
    "source": ("#7c5cff", "sources"),
    "staging": ("#2d7ff9", "staging"),
    "intermediate": ("#f2a33c", "intermediate"),
    "marts": ("#28a745", "marts"),
    "semantic": ("#c74ded", "semantic"),
    "exposure": ("#e5484d", "exposures"),
    "other": ("#8a8f98", "other"),
}


def node_label(man: Manifest, uid: str) -> str:
    node = man.all_nodes().get(uid, {})
    if uid.startswith("source."):
        return f"{node.get('source_name', '?')}.{node.get('name', uid)}"
    return node.get("name", uid.split(".")[-1])


def node_kind(man: Manifest, uid: str) -> str:
    if uid.startswith("source."):
        return "source"
    if uid.startswith("exposure."):
        return "exposure"
    node = man.nodes.get(uid)
    if not node:
        return "other"
    if node.get("resource_type") == "snapshot":
        return "staging"
    return layer_of(node)


def mermaid_id(uid: str) -> str:
    return "n" + "".join(ch if ch.isalnum() else "_" for ch in uid)


# ---------------------------------------------------------------- reports


def lineage_report(man: Manifest, model: str, direction: str, depth: int) -> None:
    uid, node = man.find_model(model)
    header(f"Lineage — {node.get('name')}")
    print(f"  layer: {layer_of(node)} · materialized: "
          f"{(node.get('config') or {}).get('materialized', '?')} · "
          f"path: {node.get('original_file_path', '?')}")

    if direction in ("up", "both"):
        ups = man.ancestors(uid, depth)
        section(f"Upstream ({len(ups)}) — what this model depends on")
        rows = sorted(
            ([node_kind(man, u), node_label(man, u), u] for u in ups),
            key=lambda r: (LAYER_ORDER.get(r[0], 0), r[1]),
        )
        table([[r[0], r[1]] for r in rows], ["kind", "node"])

    if direction in ("down", "both"):
        downs = man.descendants(uid, depth)
        models_down = [u for u in downs if u in man.nodes
                       and man.nodes[u].get("resource_type") == "model"]
        exposures_down = [u for u in downs if u.startswith("exposure.")]
        tests_down = [u for u in downs if u in man.nodes
                      and man.nodes[u].get("resource_type") in ("test", "unit_test")]

        section(f"Downstream blast radius — {len(models_down)} models, "
                f"{len(exposures_down)} exposures, {len(tests_down)} tests")
        rows = sorted(
            ([node_kind(man, u), node_label(man, u)] for u in models_down + exposures_down),
            key=lambda r: (LAYER_ORDER.get(r[0], 9), r[1]),
        )
        table(rows, ["kind", "node"])

        if exposures_down:
            print(f"\n  {Colors.RED}This change reaches {len(exposures_down)} exposure(s). "
                  f"Notify their owners before merging.{Colors.END}")
            for uid_e in exposures_down:
                exp = man.exposures.get(uid_e, {})
                owner = (exp.get("owner") or {}).get("email", "no owner")
                print(f"    - {exp.get('name')} ({exp.get('type', '?')}) — {owner}")
        elif not models_down:
            print(f"\n  {Colors.YELLOW}Nothing depends on this model. If it is a mart, "
                  f"it has no consumer — claim one or delete it.{Colors.END}")


def structure_report(man: Manifest, top: int) -> None:
    models = man.models()
    child_map = man.child_map()
    parent_map = man.parent_map()

    header(f"DAG structure — {man.project_name}")
    by_layer: Dict[str, int] = {}
    for node in models.values():
        by_layer[layer_of(node)] = by_layer.get(layer_of(node), 0) + 1
    print("  " + " · ".join(f"{k}: {v}" for k, v in sorted(by_layer.items())))
    print(f"  sources: {len(man.sources)} · exposures: {len(man.exposures)} · "
          f"metrics: {len(man.metrics)} · semantic models: {len(man.semantic_models)}")

    section(f"Highest fan-out — most direct dependents (top {top})")
    fan_out = sorted(
        ((len([c for c in child_map.get(uid, []) if c in models]), n.get("name"))
         for uid, n in models.items()),
        reverse=True,
    )[:top]
    table([[str(c), name] for c, name in fan_out if c], ["dependents", "model"])
    print("  A model with many dependents is a chokepoint: changing it is expensive, and")
    print("  it is the first place to add tests.")

    section(f"Highest fan-in — most direct dependencies (top {top})")
    fan_in = sorted(
        ((len(parent_map.get(uid, [])), n.get("name")) for uid, n in models.items()),
        reverse=True,
    )[:top]
    table([[str(c), name] for c, name in fan_in if c], ["dependencies", "model"])

    section("Deepest chains")
    memo: Dict[str, int] = {}

    def depth_of(uid: str, seen: Optional[Set[str]] = None) -> int:
        if uid in memo:
            return memo[uid]
        seen = seen or set()
        if uid in seen:
            return 0
        seen = seen | {uid}
        parents = [p for p in parent_map.get(uid, []) if p in man.nodes]
        value = 0 if not parents else 1 + max(depth_of(p, seen) for p in parents)
        memo[uid] = value
        return value

    deepest = sorted(
        ((depth_of(uid), n.get("name")) for uid, n in models.items()), reverse=True
    )[:top]
    table([[str(d), name] for d, name in deepest], ["depth", "model"])
    print("  Over 8 layers usually means redundant intermediate models.")

    orphans = [
        n.get("name")
        for uid, n in models.items()
        if layer_of(n) == "marts" and not man.descendants(uid)
    ]
    if orphans:
        section(f"Marts with no consumer ({len(orphans)})")
        table([[o] for o in orphans[:top]], ["model"])
        print("  Each costs build time, test time, and review time on every run.")


def layer_check(man: Manifest) -> int:
    header("Layer boundary check")
    problems: List[List[str]] = []
    for uid, model in man.models().items():
        layer = layer_of(model)
        for parent in model.get("depends_on", {}).get("nodes", []) or []:
            if parent.startswith("source."):
                if layer in ("marts", "intermediate"):
                    problems.append([model.get("name"), layer, "source",
                                     "references a source directly"])
                continue
            pnode = man.nodes.get(parent)
            if not pnode:
                continue
            player = layer_of(pnode)
            if LAYER_ORDER.get(layer, 0) < LAYER_ORDER.get(player, 0):
                problems.append([model.get("name"), layer, pnode.get("name"),
                                 f"depends on a {player} model — backwards"])
            elif layer == "marts" and player == "marts" and str(pnode.get("name", "")).startswith("int_"):
                problems.append([model.get("name"), layer, pnode.get("name"),
                                 "mart referencing another mart's internals"])

    cycles = man.find_cycles()
    for cycle in cycles:
        problems.append([
            man.nodes.get(cycle[0], {}).get("name", cycle[0]), "-", "-",
            "CYCLE: " + " -> ".join(man.nodes.get(u, {}).get("name", u) for u in cycle),
        ])

    if not problems:
        print(f"  {Colors.GREEN}No layer violations or cycles.{Colors.END}")
        return 0
    table(problems, ["model", "layer", "parent", "problem"], max_width=52)
    return len(problems)


def changed_report(man: Manifest, base_path: str) -> Set[str]:
    """Models whose raw SQL or config differ from a base manifest."""
    base = Manifest.load(base_path)
    changed: Set[str] = set()
    base_models = base.models()
    for uid, model in man.models().items():
        old = base_models.get(uid)
        if old is None:
            changed.add(uid)
            continue
        if (model.get("raw_code") or model.get("raw_sql")) != (
            old.get("raw_code") or old.get("raw_sql")
        ):
            changed.add(uid)
        elif model.get("config") != old.get("config"):
            changed.add(uid)

    header(f"Changed vs {base_path}")
    if not changed:
        print("  No model changes.")
        return changed
    impacted: Set[str] = set()
    for uid in changed:
        impacted |= man.descendants(uid)
    impacted_models = {u for u in impacted if u in man.nodes
                       and man.nodes[u].get("resource_type") == "model"} - changed
    impacted_exposures = {u for u in impacted if u.startswith("exposure.")}

    print(f"  {len(changed)} changed · {len(impacted_models)} downstream models affected "
          f"· {len(impacted_exposures)} exposures affected")
    table(sorted([[node_label(man, u), node_kind(man, u)] for u in changed]),
          ["changed model", "layer"])
    if impacted_exposures:
        section("Exposures affected — notify these owners")
        for uid_e in sorted(impacted_exposures):
            exp = man.exposures.get(uid_e, {})
            print(f"  - {exp.get('name')} ({exp.get('type','?')}) — "
                  f"{(exp.get('owner') or {}).get('email', 'no owner')}")
    print(f"\n  CI selector: dbt build --select state:modified+ --defer --state {os.path.dirname(base_path) or '.'}/")
    return changed


# ---------------------------------------------------------------- mermaid


def mermaid(man: Manifest, focus: Optional[str], depth: int,
            highlight: Optional[Set[str]] = None, max_nodes: int = 120) -> str:
    if focus:
        uid, _ = man.find_model(focus)
        keep = {uid} | man.ancestors(uid, depth) | man.descendants(uid, depth)
    else:
        keep = set(man.models()) | set(man.sources) | set(man.exposures)

    keep = {
        u for u in keep
        if u.startswith(("source.", "exposure."))
        or (u in man.nodes and man.nodes[u].get("resource_type") in ("model", "snapshot"))
    }

    truncated = False
    if len(keep) > max_nodes:
        truncated = True
        # Prefer the focus node, exposures, and highest-degree models.
        child_map = man.child_map()
        ranked = sorted(
            keep,
            key=lambda u: (
                0 if focus and u == man.find_model(focus)[0] else
                1 if u.startswith("exposure.") else 2,
                -len(child_map.get(u, [])),
            ),
        )
        keep = set(ranked[:max_nodes])

    lines = ["```mermaid", "graph LR"]
    groups: Dict[str, List[str]] = {}
    for uid in sorted(keep):
        groups.setdefault(node_kind(man, uid), []).append(uid)

    for kind in ("source", "staging", "intermediate", "marts", "semantic", "exposure", "other"):
        members = groups.get(kind)
        if not members:
            continue
        _, title = MERMAID_STYLE[kind]
        lines.append(f'  subgraph {title}["{title}"]')
        for uid in members:
            shape_l, shape_r = ("[(", ")]") if kind == "source" else (
                (">", "]") if kind == "exposure" else ("[", "]")
            )
            lines.append(f'    {mermaid_id(uid)}{shape_l}"{node_label(man, uid)}"{shape_r}')
        lines.append("  end")

    parent_map = man.parent_map()
    for uid in sorted(keep):
        for parent in parent_map.get(uid, []) or []:
            if parent in keep:
                lines.append(f"  {mermaid_id(parent)} --> {mermaid_id(uid)}")

    for kind, (colour, _) in MERMAID_STYLE.items():
        members = groups.get(kind)
        if members:
            lines.append(f"  classDef {kind} fill:{colour},stroke:#333,color:#fff;")
            lines.append(f"  class {','.join(mermaid_id(u) for u in members)} {kind};")

    if highlight:
        hl = [mermaid_id(u) for u in highlight if u in keep]
        if hl:
            lines.append("  classDef changed fill:#e5484d,stroke:#000,stroke-width:3px,color:#fff;")
            lines.append(f"  class {','.join(hl)} changed;")

    lines.append("```")
    if truncated:
        lines.append("")
        lines.append(f"_Truncated to {max_nodes} nodes. Use `--model <name> --depth 2` "
                     f"to scope, or raise `--max-nodes`._")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Analyze a dbt Core DAG.")
    ap.add_argument("--manifest", default="target/manifest.json")
    ap.add_argument("--model", help="focus on one model")
    ap.add_argument("--direction", choices=["up", "down", "both"], default="both")
    ap.add_argument("--depth", type=int, default=99)
    ap.add_argument("--mermaid", action="store_true", help="emit a Mermaid diagram")
    ap.add_argument("--max-nodes", type=int, default=120, help="Mermaid node cap")
    ap.add_argument("--check-layers", action="store_true",
                    help="report layer-boundary violations and cycles; exit 1 if any")
    ap.add_argument("--changed-vs", help="diff against a base manifest.json")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()

    man = Manifest.load(args.manifest)
    exit_code = 0
    highlight: Optional[Set[str]] = None

    if args.changed_vs:
        highlight = changed_report(man, args.changed_vs)
    if args.check_layers:
        exit_code = 1 if layer_check(man) else 0
    if args.model and not args.mermaid:
        lineage_report(man, args.model, args.direction, args.depth)
    if not any([args.model, args.check_layers, args.changed_vs, args.mermaid]):
        structure_report(man, args.top)

    if args.mermaid:
        if args.model:
            lineage_report(man, args.model, args.direction, args.depth)
        print()
        print(mermaid(man, args.model, args.depth, highlight, args.max_nodes))

    if args.json_out:
        payload: Dict[str, Any] = {"project": man.project_name}
        if args.model:
            uid, node = man.find_model(args.model)
            payload["model"] = node.get("name")
            payload["upstream"] = sorted(man.ancestors(uid, args.depth))
            payload["downstream"] = sorted(man.descendants(uid, args.depth))
        if highlight is not None:
            payload["changed"] = sorted(highlight)
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"\nWrote {args.json_out}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
