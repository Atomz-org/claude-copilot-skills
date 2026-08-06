#!/usr/bin/env python3
"""Emit the semantic-layer fragment for graphify: joins, semantic models, metrics.

The fourth fragment emitter, and it exists to close a measured hole. The Graphify-first
rule makes `graphify query` an agent's first move, but before this fragment the graph
held none of the knowledge a connector-onboarding agent actually orients on:

- **0 join edges.** All 101 of enhanza's FK relationships (dbt `relationships` tests)
  were absent — and none are recoverable from `parent_map`, because a fact model does
  not `ref()` the dimension it joins to. The join lives *only* in the test.
- **0 semantic-layer nodes.** The MetricFlow semantic models, metrics, and saved
  queries never entered the graph, so "which metrics touch fact_sales" was a
  whole-file read of `_metrics.yml` plus `semantic-metrics.md` (~2.3k tokens) rather
  than a scoped query.

Everything here derives from **manifest.json, never from wren/**. WrenAI's
`relationships.yml` is the importer's projection of the same relationships tests, so
reading the manifest keeps one source of truth — and keeps the `graph` stage (which
runs before `wren`) from consuming a previous generation's projection.

What it emits:

- `joins_to` edges, child model → parent model, from `relationships` tests. Attrs:
  `dbt_fk_column` (child side), `dbt_parent_field` (parent side), and `dbt_join_type`
  derived from unique tests on the child FK column — `one_to_one` when unique-tested,
  else `many_to_one`; never guessed beyond that (rule 5). The parent comes from
  `depends_on.nodes` minus the attached child — never from regexing the jinja in
  `kwargs.to`.
- one node per **semantic model**, edged `describes` → its backing model.
- one node per **metric**, edged `measures` → its semantic model and `composes` →
  the metrics a ratio/derived metric is built from.
- one node per **saved query** (id prefixed `saved_query_` — it shares `_metrics.yml`
  with metrics, and an unprefixed name would collide with a same-named metric),
  edged `bundles` → each member metric.

Model-node endpoints are resolved through `model_source_file()` + `node_id()` — the
same path the other emitters use — because a name rule that misses makes `build_merge`
mint a silent stub node beside the real one, and nothing errors.

The relation vocabulary is closed: `joins_to, describes, measures, composes, bundles`.
`tests/test_semantic_layer_to_graphify.py` pins it, exactly as `references/calls` is
pinned for the model emitter.

Usage:
    python3 scripts/semantic_layer_to_graphify.py --manifest <path> [--dry-run]
    python3 scripts/semantic_layer_to_graphify.py --manifest <path> --merge-graphify

Ordering rule unchanged and inherited: merge only inside `use_case_sync.py`'s `graph`
stage (or manually BEFORE any `graphify update`) — a rebuild after the merge deletes
every merged node.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _manifest import Manifest, die  # noqa: E402
from _paths import REPO  # noqa: E402
import dbt_manifest_to_graphify as emitter  # noqa: E402

RELATIONS = ("joins_to", "describes", "measures", "composes", "bundles")

DEFAULT_OUT = "graphify-out/.graphify_semantic_layer.json"


def _blank(source_file: str) -> Dict[str, Any]:
    """The nine envelope keys every graphify node must carry."""
    return {
        "id": "",
        "label": "",
        "file_type": "code",
        "source_file": source_file,
        "source_location": None,
        "source_url": None,
        "captured_at": None,
        "author": None,
        "contributor": None,
    }


def _edge(source: str, target: str, relation: str, source_file: str,
          **attrs: Any) -> Dict[str, Any]:
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "confidence": "EXTRACTED",
        "confidence_score": 1.0,
        "source_file": source_file,
        "source_location": None,
        "weight": 1.0,
        **attrs,
    }


def _model_ids(man: Manifest, project_root: Path) -> Dict[str, str]:
    """manifest unique_id -> graph node id, through the on-disk path formula."""
    project_rel = emitter._rel(project_root)
    prefixes = emitter.package_prefixes(man, project_root)
    out: Dict[str, str] = {}
    for uid, node in man.nodes.items():
        if node.get("resource_type") not in ("model", "snapshot", "seed"):
            continue
        source_file = emitter.model_source_file(node, man, project_rel, prefixes)
        if source_file.endswith(".sql"):
            out[uid] = emitter.node_id(source_file)
        else:
            out[uid] = emitter.node_id(source_file, node.get("name", ""))
    return out


def _unique_columns(man: Manifest) -> Dict[str, Set[str]]:
    """model unique_id -> columns carrying a `unique` test. Cardinality evidence."""
    out: Dict[str, Set[str]] = {}
    for node in man.nodes.values():
        if node.get("resource_type") != "test":
            continue
        meta = node.get("test_metadata") or {}
        if meta.get("name") != "unique":
            continue
        column = node.get("column_name")
        attached = node.get("attached_node")
        if column and attached:
            out.setdefault(attached, set()).add(column)
    return out


def join_edges(man: Manifest, model_ids: Dict[str, str],
               project_rel: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """One `joins_to` edge per relationships test, plus the skipped ones with reasons."""
    unique_cols = _unique_columns(man)
    edges: List[Dict[str, Any]] = []
    skipped: List[str] = []

    for uid, node in sorted(man.nodes.items()):
        if node.get("resource_type") != "test":
            continue
        meta = node.get("test_metadata") or {}
        if meta.get("name") != "relationships":
            continue

        child = node.get("attached_node")
        parents = [p for p in (node.get("depends_on", {}).get("nodes") or [])
                   if p != child]
        if not child or len(parents) != 1:
            skipped.append(f"{uid}: expected exactly one parent, got {parents}")
            continue
        parent = parents[0]
        if child not in model_ids or parent not in model_ids:
            skipped.append(f"{uid}: endpoint not a modelled node "
                           f"({child if child not in model_ids else parent})")
            continue

        fk_column = node.get("column_name") or ""
        field = (meta.get("kwargs") or {}).get("field") or ""
        attrs: Dict[str, Any] = {}
        if fk_column:
            attrs["dbt_fk_column"] = fk_column
            attrs["dbt_join_type"] = (
                "one_to_one" if fk_column in unique_cols.get(child, set())
                else "many_to_one"
            )
        if field:
            attrs["dbt_parent_field"] = field

        source_file = node.get("original_file_path") or ""
        edges.append(_edge(model_ids[child], model_ids[parent], "joins_to",
                           f"{project_rel}/{source_file}" if source_file else project_rel,
                           **attrs))
    return edges, skipped


def build_fragment(man: Manifest, project_root: Path) -> Dict[str, Any]:
    project_rel = emitter._rel(project_root)
    model_ids = _model_ids(man, project_root)

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]]
    minted: Set[str] = set()

    def mint(node: Dict[str, Any]) -> Optional[str]:
        if node["id"] in minted:
            return None
        minted.add(node["id"])
        nodes.append(node)
        return node["id"]

    edges, join_skipped = join_edges(man, model_ids, project_rel)

    # -- semantic models -----------------------------------------------------------
    sm_ids: Dict[str, str] = {}
    for uid, sm in sorted(man.semantic_models.items()):
        rel_file = f"{project_rel}/{sm.get('original_file_path', '')}"
        gid = emitter.node_id(rel_file, sm.get("name", ""))
        sm_ids[uid] = gid
        node = _blank(rel_file)
        node.update({
            "id": gid,
            "label": f"semantic model: {sm.get('name', '')}",
            "dbt_resource_type": "semantic_model",
            "dbt_unique_id": uid,
            "dbt_description": (sm.get("description") or "").strip(),
            "dbt_agg_time_dimension":
                (sm.get("defaults") or {}).get("agg_time_dimension") or "",
            "entities": ", ".join(
                f"{e.get('name')}:{e.get('type')}:{e.get('expr') or e.get('name')}"
                for e in sm.get("entities") or []),
            "measures": ", ".join(
                f"{m.get('name')}:{m.get('agg')}:{m.get('expr') or m.get('name')}"
                for m in sm.get("measures") or []),
            "dimensions": ", ".join(
                f"{d.get('name')}:{d.get('type')}"
                for d in sm.get("dimensions") or []),
        })
        mint(node)
        for dep in sm.get("depends_on", {}).get("nodes") or []:
            if dep in model_ids:
                edges.append(_edge(gid, model_ids[dep], "describes", rel_file))

    # -- metrics -------------------------------------------------------------------
    metric_ids: Dict[str, str] = {}
    for uid, metric in sorted(man.metrics.items()):
        rel_file = f"{project_rel}/{metric.get('original_file_path', '')}"
        gid = emitter.node_id(rel_file, metric.get("name", ""))
        metric_ids[uid] = gid

    for uid, metric in sorted(man.metrics.items()):
        rel_file = f"{project_rel}/{metric.get('original_file_path', '')}"
        gid = metric_ids[uid]
        tp = metric.get("type_params") or {}
        measure = (tp.get("measure") or {}).get("name") or ""
        filters = metric.get("filter") or {}
        filter_sql = "; ".join(
            (f.get("where_sql_template") or "").strip()
            for f in (filters.get("where_filters") or []) if f
        )
        node = _blank(rel_file)
        node.update({
            "id": gid,
            "label": f"metric: {metric.get('name', '')}",
            "dbt_resource_type": "metric",
            "dbt_unique_id": uid,
            "dbt_metric_type": metric.get("type") or "",
            "dbt_metric_label": metric.get("label") or "",
            "dbt_description": (metric.get("description") or "").strip(),
            "dbt_measure": measure,
            "dbt_filter": filter_sql,
        })
        mint(node)
        for dep in metric.get("depends_on", {}).get("nodes") or []:
            if dep in sm_ids:
                edges.append(_edge(gid, sm_ids[dep], "measures", rel_file))
            elif dep in metric_ids:
                edges.append(_edge(gid, metric_ids[dep], "composes", rel_file))

    # -- saved queries -------------------------------------------------------------
    for uid, sq in sorted(man.saved_queries.items()):
        rel_file = f"{project_rel}/{sq.get('original_file_path', '')}"
        # Prefixed entity: saved queries share _metrics.yml with metrics, and a
        # saved query named after a metric would otherwise take the metric's id.
        gid = emitter.node_id(rel_file, f"saved_query_{sq.get('name', '')}")
        qp = sq.get("query_params") or {}
        node = _blank(rel_file)
        node.update({
            "id": gid,
            "label": f"saved query: {sq.get('name', '')}",
            "dbt_resource_type": "saved_query",
            "dbt_unique_id": uid,
            "dbt_description": (sq.get("description") or "").strip(),
            "group_by": ", ".join(qp.get("group_by") or []),
        })
        mint(node)
        for dep in sq.get("depends_on", {}).get("nodes") or []:
            if dep in metric_ids:
                edges.append(_edge(gid, metric_ids[dep], "bundles", rel_file))

    # Canonical ordering: content decides the bytes, not dict order (same rule as
    # the model emitter, and for the same reason — deterministic diffs).
    nodes.sort(key=lambda n: json.dumps(n, sort_keys=True))
    seen_edges: Set[str] = set()
    unique_edges: List[Dict[str, Any]] = []
    for edge in edges:
        key = json.dumps(edge, sort_keys=True)
        if key not in seen_edges:
            seen_edges.add(key)
            unique_edges.append(edge)
    unique_edges.sort(key=lambda e: json.dumps(e, sort_keys=True))

    return {
        "nodes": nodes,
        "edges": unique_edges,
        "hyperedges": [],
        "input_tokens": 0,
        "output_tokens": 0,
        # Diagnostics for the caller; stripped before writing (the envelope is pinned).
        "_join_skipped": join_skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--project-root", default=None,
                        help="dbt project root (default: the manifest's grandparent)")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--merge-graphify", action="store_true",
                        help="merge the fragment into graphify-out/graph.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        die(f"no manifest at {manifest_path} — run dbt parse (or artifacts/refresh.sh)")
    man = Manifest.load(str(manifest_path))
    project_root = (Path(args.project_root) if args.project_root
                    else manifest_path.resolve().parent.parent)

    rel_tests = sum(
        1 for n in man.nodes.values()
        if n.get("resource_type") == "test"
        and (n.get("test_metadata") or {}).get("name") == "relationships"
    )
    if not (rel_tests or man.semantic_models or man.metrics or man.saved_queries):
        # Nothing to emit is a state, not a failure: a project with no relationships
        # tests and no semantic layer has no wren-tier knowledge to merge yet.
        msg = ("skip: no relationships tests and no semantic layer in this manifest — "
               "add dbt relationships tests or models/semantic/ first")
        print(json.dumps({"status": "skip", "reason": msg}) if args.format == "json"
              else msg)
        return 0

    fragment = build_fragment(man, project_root)
    join_skipped = fragment.pop("_join_skipped")

    counts = {
        "joins": sum(1 for e in fragment["edges"] if e["relation"] == "joins_to"),
        "semantic_models": sum(1 for n in fragment["nodes"]
                               if n.get("dbt_resource_type") == "semantic_model"),
        "metrics": sum(1 for n in fragment["nodes"]
                       if n.get("dbt_resource_type") == "metric"),
        "saved_queries": sum(1 for n in fragment["nodes"]
                             if n.get("dbt_resource_type") == "saved_query"),
        "nodes": len(fragment["nodes"]),
        "edges": len(fragment["edges"]),
        "join_tests_skipped": len(join_skipped),
    }

    if args.dry_run:
        payload = {"status": "dry-run", **counts, "skipped": join_skipped}
        print(json.dumps(payload, indent=2) if args.format == "json" else
              f"dry-run: would emit {counts['nodes']} nodes, {counts['edges']} edges "
              f"({counts['joins']} joins, {counts['semantic_models']} semantic models, "
              f"{counts['metrics']} metrics, {counts['saved_queries']} saved queries)"
              + (f"; {len(join_skipped)} join test(s) skipped" if join_skipped else ""))
        return 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fragment, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    if args.format == "json":
        print(json.dumps({"status": "ok", "fragment": str(out_path), **counts}))
    else:
        print(f"wrote {out_path}: {counts['nodes']} nodes, {counts['edges']} edges "
              f"({counts['joins']} joins_to, {counts['semantic_models']} semantic "
              f"models, {counts['metrics']} metrics, "
              f"{counts['saved_queries']} saved queries)")
        for reason in join_skipped:
            print(f"  [skip] {reason}", file=sys.stderr)

    if args.merge_graphify:
        rc = emitter.merge_into_graph(out_path, project_root)
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
