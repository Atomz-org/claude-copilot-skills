#!/usr/bin/env python3
"""Turn a dbt Core manifest into a graphify extraction fragment.

graphify has no SQL parser. `.sql` is classified as code, handed to the AST extractor,
and the extractor finds no symbols in it — so every dbt model lands in the graph as an
isolated file node with no edges. Measured on this repository before this script existed:
393 `.sql` nodes, 393 of them at degree 0. The dbt DAG, which is the most important
structure in a dbt project, was entirely absent, and the only dbt entity with any edges
was a `schema.yml` node whose 33 edges came from `ref()` calls the semantic subagents
happened to read out of `relationships` tests.

dbt already computes the true DAG. `manifest.json` carries `depends_on` per node and
`parent_map`/`child_map` over the whole project, so the edge set graphify cannot derive is
sitting in an artifact the project produces anyway. Every edge emitted here is EXTRACTED
with confidence 1.0 — dbt compiled it, nothing is inferred.

The node IDs are the whole trick. graphify mints a file node's ID from the repo-relative
path with the extension dropped and every non-alphanumeric run collapsed to `_`:

    skill-packs/.../models/fortnox/fortnox_bi/fortnox_bi_dim_company.sql
    -> skill_packs_..._models_fortnox_fortnox_bi_fortnox_bi_dim_company

`node_id()` reproduces that byte for byte, so `build_merge` *replaces* the existing
degree-0 node rather than adding a second one beside it. The graph gains edges and
attributes on the nodes it already had; it does not gain a parallel set of ghosts.

Coverage is checked, not assumed. A dbt manifest only contains the models that were
enabled at parse time, and in a connector-gated project like enhanza-analytics that is a
function of the `--vars` whoever ran dbt last happened to pass. The manifest committed to
this repository before this script held 72 of 359 models; ingesting it would have produced
an accurate graph of a fifth of the project with nothing to indicate the rest was missing.
`--check-coverage` (on by default) compares the manifest against the `.sql` files on disk
and refuses to emit when the gap exceeds `--coverage-threshold`.

Usage:
    # emit an extraction fragment
    python3 scripts/dbt_manifest_to_graphify.py \\
        --manifest skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project/target/manifest.json \\
        --out graphify-out/.graphify_extract.json

    # emit and merge straight into graphify-out/graph.json
    python3 scripts/dbt_manifest_to_graphify.py --manifest <path> --merge

    # what would be emitted, and the coverage check, without writing
    python3 scripts/dbt_manifest_to_graphify.py --manifest <path> --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _manifest import Manifest, die  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# How many names a capped list carries. Enough to recognise the pattern, few enough that a
# pathological run costs a line rather than a page.
SAMPLE = 10

# dbt resource types that become nodes. `test` is deliberately absent: 193 test nodes on a
# 359-model project buries the DAG in leaf noise, and what a reader actually wants to know
# — is the primary key tested — is one boolean. Tests become attributes on the model they
# cover, and `relationships` tests are already edges via depends_on.
MODELLED_TYPES = ("model", "snapshot", "seed", "analysis", "exposure", "metric")

# A model's layer, read off the path rather than the name. Order matters: the first match
# wins, so `staging/erp` resolves to `unified` before the generic `staging` rule.
LAYER_RULES: Tuple[Tuple[str, str], ...] = (
    ("models/staging/erp", "unified"),
    ("models/staging", "staging"),
    ("models/demo", "demo"),
    ("models/app", "app"),
    ("models/logic_bi", "mart"),
)


def node_id(rel_path: str, entity: str = "") -> str:
    """Reproduce graphify's node-ID formula exactly.

    Full repo-relative path, extension dropped, every non-alphanumeric run collapsed to a
    single `_`, lowercased. An `entity` is appended the same way when the node is a symbol
    inside the file rather than the file itself.

    This must match what graphify's AST extractor already minted for the same file, or the
    merge produces a duplicate instead of an upgrade. `tests/test_dbt_manifest_to_graphify.py`
    pins it against real IDs taken from graphify-out/graph.json.
    """
    stem = os.path.splitext(rel_path)[0]
    parts = [stem, entity] if entity else [stem]
    slug = "_".join(parts)
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", slug).strip("_").lower()
    return slug


def _rel(path: Path) -> str:
    """Repo-relative POSIX path, which is the form graphify stores in `source_file`."""
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def project_root_of(manifest_path: Path) -> Path:
    """The dbt project directory a manifest belongs to.

    `original_file_path` in the manifest is relative to the dbt project root, not the repo
    root, so the two have to be joined to get a path graphify would recognise. Walk up from
    the manifest until a dbt_project.yml appears — this handles both `<project>/target/` and
    the committed `<use-case>/artifacts/prod/` layout.
    """
    for candidate in [manifest_path.parent, *manifest_path.parents]:
        if (candidate / "dbt_project.yml").exists():
            return candidate
    # artifacts/prod/manifest.json -> the sibling dbt_project/ of the use-case
    for candidate in manifest_path.parents:
        sibling = candidate / "dbt_project"
        if (sibling / "dbt_project.yml").exists():
            return sibling
    die(
        f"could not locate a dbt_project.yml above {manifest_path}.\n"
        f"  Pass --project-root explicitly."
    )
    raise SystemExit(2)  # unreachable; keeps type checkers quiet


def layer_of(rel_in_project: str) -> str:
    for prefix, layer in LAYER_RULES:
        if rel_in_project.startswith(prefix):
            return layer
    return "bi"


def connector_of(node: Dict[str, Any], rel_in_project: str) -> Optional[str]:
    """The connector a model belongs to.

    Tags are the project's own declaration of this and are preferred; the directory is the
    fallback for a model whose tags were never set. Layer tags are not connectors.
    """
    layer_tags = {"staging", "bi", "mart", "flat", "reports", "demo", "app", "unified", "scaffold", "logic"}
    for tag in node.get("tags", []) or []:
        if tag not in layer_tags:
            return tag
    parts = rel_in_project.split("/")
    if len(parts) > 2 and parts[1] == "staging":
        return parts[2]
    if len(parts) > 1 and parts[1].endswith("_bi"):
        return parts[1][: -len("_bi")]
    return None


def collect_test_info(man: Manifest) -> Dict[str, Dict[str, Any]]:
    """Per-model test summary: which generic tests ran, and whether a PK is covered.

    A primary key counts as tested when the same column carries both `unique` and
    `not_null` — rule 21 in .claude/rules/analytics-engineering-rules.md. Testing them on
    different columns is not a tested key, so the two sets are intersected rather than
    counted.
    """
    info: Dict[str, Dict[str, Any]] = {}
    unique_cols: Dict[str, Set[str]] = {}
    notnull_cols: Dict[str, Set[str]] = {}

    for node in man.nodes.values():
        if node.get("resource_type") != "test":
            continue
        meta = node.get("test_metadata") or {}
        name = meta.get("name", "")
        column = node.get("column_name")
        for parent in node.get("depends_on", {}).get("nodes", []) or []:
            entry = info.setdefault(parent, {"tests": set(), "test_count": 0})
            entry["test_count"] += 1
            if name:
                entry["tests"].add(name)
            if column and name == "unique":
                unique_cols.setdefault(parent, set()).add(column)
            if column and name == "not_null":
                notnull_cols.setdefault(parent, set()).add(column)

    for uid, entry in info.items():
        entry["tests"] = sorted(entry["tests"])
        keys = unique_cols.get(uid, set()) & notnull_cols.get(uid, set())
        entry["pk_tested"] = bool(keys)
        entry["tested_key"] = sorted(keys)
    return info


def _column_edges(
    man: Manifest,
    project_rel: str,
    seen: Dict[str, str],
    nodes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Column nodes and `derives_from` edges, appended to `nodes` in place.

    A column node hangs off its model's node ID with a `_col_<name>` suffix, so
    `fortnox_bi_dim_company_staging.OrgName` is reachable from the model and the whole chain
    `OrgName <- companyName` survives as edges rather than as an attribute nobody can
    traverse. Only columns that participate in lineage get a node — a documented column
    nobody derives from is already an attribute on the model.
    """
    import dbt_column_lineage as lineage_mod

    if lineage_mod.sqlglot is None:
        print(
            "  (column lineage skipped: sqlglot not installed — pip install sqlglot)",
            file=sys.stderr,
        )
        return []

    lineage = lineage_mod.build_lineage(man)
    by_model_name: Dict[str, str] = {}
    for uid, gid in seen.items():
        node = man.nodes.get(uid) or man.sources.get(uid) or {}
        name = node.get("name")
        if not name:
            continue
        by_model_name.setdefault(name, gid)
        # `strip_jinja` rewrites `{{ source('fortnox_api','company_settings') }}` to the
        # identifier `fortnox_api__company_settings`, so the lineage refers to sources by
        # that joined form. Without this alias every staging model's lineage — which is
        # most of it, and the only place raw column names appear — resolves to nothing.
        source_name = node.get("source_name")
        if source_name:
            by_model_name.setdefault(
                f"{source_name}{lineage_mod.SOURCE_SEP}{name}", gid
            )

    def column_node(model_name: str, column: str) -> Optional[str]:
        parent = by_model_name.get(model_name)
        if not parent:
            return None
        gid = f"{parent}_col_{re.sub(r'[^a-zA-Z0-9]+', '_', column).strip('_').lower()}"
        if gid not in minted:
            minted.add(gid)
            nodes.append({
                "id": gid,
                "label": f"{model_name}.{column}",
                "file_type": "code",
                "source_file": next(
                    (n["source_file"] for n in nodes if n["id"] == parent), None
                ),
                "source_location": None,
                "source_url": None,
                "captured_at": None,
                "author": None,
                "contributor": None,
                "dbt_resource_type": "column",
                "dbt_model": model_name,
                "dbt_column": column,
            })
        return gid

    minted: Set[str] = set()
    out: List[Dict[str, Any]] = []
    for edge in lineage["edges"]:
        if edge.column in ("*", "(macro)") or not edge.upstream_model:
            continue
        child = column_node(edge.model, edge.column)
        parent = column_node(edge.upstream_model, edge.upstream_column)
        if not child or not parent or child == parent:
            continue
        out.append({
            "source": parent,
            "target": child,
            "relation": "derives_from",
            # sqlglot read this out of the SQL; the transform kind is observed, not guessed.
            "confidence": "EXTRACTED",
            "confidence_score": 1.0,
            "dbt_transform": edge.kind,
            "source_file": None,
            "source_location": None,
            "weight": 1.0,
        })
    return out


def build_fragment(
    man: Manifest,
    project_root: Path,
    include_sources: bool = True,
    include_columns: bool = False,
) -> Dict[str, Any]:
    """The graphify extraction fragment for one dbt project."""
    project_rel = _rel(project_root)
    tests = collect_test_info(man)

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen: Dict[str, str] = {}  # unique_id -> graphify node id
    by_connector: Dict[str, List[str]] = {}

    # package_name -> path prefix inside the project. `original_file_path` is relative to
    # the node's *package* root, so a model in packages/fortnox would otherwise claim
    # `<project>/models/...` — a path that does not exist — and its graph node id would
    # collide with a root model of the same relative path. First-party packages are the
    # ones with a dbt_project.yml under packages/; dbt_packages/ (installed symlinks) is
    # deliberately not scanned, or every package file would appear twice.
    pkg_prefix: Dict[str, str] = {man.project_name: ""}
    for pkg_yml in sorted(project_root.glob("packages/*/dbt_project.yml")):
        match = re.search(
            r"^name:\s*['\"]?([A-Za-z0-9_]+)", pkg_yml.read_text(encoding="utf-8"), re.MULTILINE
        )
        if match:
            pkg_prefix[match.group(1)] = f"packages/{pkg_yml.parent.name}"

    def file_path_of(node: Dict[str, Any]) -> str:
        prefix = pkg_prefix.get(node.get("package_name") or man.project_name, "")
        base = f"{project_rel}/{prefix}".rstrip("/")
        return f"{base}/{node.get('original_file_path', '')}".rstrip("/")

    # ---- models, snapshots, seeds, exposures, metrics ---------------------------------
    for uid, node in man.all_nodes().items():
        rtype = node.get("resource_type")
        if rtype not in MODELLED_TYPES:
            continue
        rel_in_project = node.get("original_file_path", "")
        if not rel_in_project:
            continue
        source_file = file_path_of(node)
        # Models are file nodes in graphify (one .sql file, no symbols found). Exposures and
        # metrics live inside a .yml alongside others, so they carry an entity suffix.
        entity = "" if rel_in_project.endswith(".sql") else node.get("name", "")
        gid = node_id(source_file, entity)
        seen[uid] = gid

        config = node.get("config", {}) or {}
        connector = connector_of(node, rel_in_project)
        test_entry = tests.get(uid, {})
        nodes.append(
            {
                "id": gid,
                "label": node.get("name", uid),
                "file_type": "code",
                "source_file": source_file,
                "source_location": None,
                "source_url": None,
                "captured_at": None,
                "author": None,
                "contributor": None,
                # dbt-specific attributes. graphify preserves unknown node attributes, and
                # these are what make a query like "which fortnox marts have no tested key"
                # answerable from the graph alone.
                "dbt_resource_type": rtype,
                "dbt_unique_id": uid,
                "dbt_alias": node.get("alias") or node.get("name"),
                "dbt_schema": config.get("schema") or node.get("schema"),
                "dbt_materialized": config.get("materialized"),
                "dbt_tags": sorted(node.get("tags", []) or []),
                "dbt_layer": layer_of(rel_in_project),
                "dbt_connector": connector,
                "dbt_description": (node.get("description") or "").strip() or None,
                "dbt_column_count": len(node.get("columns", {}) or {}),
                "dbt_test_count": test_entry.get("test_count", 0),
                "dbt_tests": test_entry.get("tests", []),
                "dbt_pk_tested": test_entry.get("pk_tested", False),
                "dbt_tested_key": test_entry.get("tested_key", []),
            }
        )
        if connector:
            by_connector.setdefault(connector, []).append(gid)

    # ---- project macros ----------------------------------------------------------------
    # A macro is a `.sql` file that graphify's AST pass leaves isolated for the same reason
    # models are: it is Jinja, not a language the extractor parses. In this project they are
    # not incidental — `erp_union()` builds every model in the unified layer and
    # `auto_config()` sets the alias and enable flag for most of the rest, so a graph
    # without them is missing the thing that generates a third of the SQL. Package macros
    # (dbt_utils, dbt core) are excluded: they are vendored and not part of this repo.
    for uid, node in man.macros.items():
        # First-party macros only — the root project and its local packages. dbt_utils and
        # dbt-internal macros are vendored, not part of this repo.
        if node.get("package_name") not in pkg_prefix:
            continue
        rel_in_project = node.get("original_file_path", "")
        if not rel_in_project:
            continue
        source_file = file_path_of(node)
        gid = node_id(source_file)
        seen[uid] = gid
        nodes.append(
            {
                "id": gid,
                "label": node.get("name", uid),
                "file_type": "code",
                "source_file": source_file,
                "source_location": None,
                "source_url": None,
                "captured_at": None,
                "author": None,
                "contributor": None,
                "dbt_resource_type": "macro",
                "dbt_unique_id": uid,
                "dbt_description": (node.get("description") or "").strip() or None,
            }
        )

    # Macro -> node edges. `parent_map` covers ref()/source() only, so a macro dependency is
    # invisible there and has to come off each node's own depends_on.
    for uid, node in list(man.all_nodes().items()) + list(man.macros.items()):
        child = seen.get(uid)
        if not child:
            continue
        for macro_uid in (node.get("depends_on", {}) or {}).get("macros", []) or []:
            parent = seen.get(macro_uid)
            if not parent or parent == child:
                continue
            edges.append(
                {
                    "source": parent,
                    "target": child,
                    "relation": "calls",
                    "confidence": "EXTRACTED",
                    "confidence_score": 1.0,
                    "source_file": None,
                    "source_location": None,
                    "weight": 1.0,
                }
            )

    # ---- sources ----------------------------------------------------------------------
    if include_sources:
        for uid, node in man.sources.items():
            rel_in_project = node.get("original_file_path", "")
            if not rel_in_project:
                continue
            source_file = file_path_of(node)
            entity = f"{node.get('source_name', '')}_{node.get('name', '')}"
            gid = node_id(source_file, entity)
            seen[uid] = gid
            freshness = node.get("freshness") or {}
            nodes.append(
                {
                    "id": gid,
                    "label": f"{node.get('source_name')}.{node.get('name')}",
                    "file_type": "code",
                    "source_file": source_file,
                    "source_location": None,
                    "source_url": None,
                    "captured_at": None,
                    "author": None,
                    "contributor": None,
                    "dbt_resource_type": "source",
                    "dbt_unique_id": uid,
                    "dbt_source_name": node.get("source_name"),
                    "dbt_loaded_at_field": node.get("loaded_at_field"),
                    "dbt_has_freshness": bool(
                        freshness.get("warn_after", {}).get("count")
                        or freshness.get("error_after", {}).get("count")
                    ),
                    "dbt_description": (node.get("description") or "").strip() or None,
                }
            )

    # ---- edges: the DAG dbt already computed -------------------------------------------
    # parent_map is authoritative and covers tests too; tests are filtered out because they
    # are not nodes here. Direction is parent -> child, matching graphify's `references`.
    for child_uid, parents in (man.data.get("parent_map") or {}).items():
        child = seen.get(child_uid)
        if not child:
            continue
        for parent_uid in parents or []:
            parent = seen.get(parent_uid)
            if not parent or parent == child:
                continue
            edges.append(
                {
                    "source": parent,
                    "target": child,
                    "relation": "references",
                    "confidence": "EXTRACTED",
                    "confidence_score": 1.0,
                    "source_file": None,
                    "source_location": None,
                    "weight": 1.0,
                }
            )

    # ---- column-level lineage ----------------------------------------------------------
    # Off by default. `manifest.json` has no column lineage in it — deriving it means
    # parsing every model's SQL, and the result roughly doubles the graph (3058 -> ~5600
    # nodes on this project). That is worth it to trace a column across layers and useless
    # if you only ever ask about models, so it is a flag rather than a default.
    if include_columns:
        edges.extend(_column_edges(man, project_rel, seen, nodes))

    # ---- hyperedges: one per connector -------------------------------------------------
    # A connector is a genuine n-ary grouping — its staging models, adapters, and BI models
    # participate in one delivery unit that no pairwise edge expresses.
    hyperedges = [
        {
            "id": f"dbt_connector_{re.sub(r'[^a-z0-9]+', '_', connector.lower())}",
            "label": f"{connector} connector",
            "nodes": sorted(members),
            "relation": "participate_in",
            "confidence": "EXTRACTED",
            "confidence_score": 1.0,
            "source_file": f"{project_rel}/dbt_project.yml",
        }
        for connector, members in sorted(by_connector.items())
        if len(members) >= 3
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "hyperedges": hyperedges,
        "input_tokens": 0,
        "output_tokens": 0,
    }


def coverage(man: Manifest, project_root: Path) -> Dict[str, Any]:
    """Models in the manifest vs `.sql` files under the model paths on disk.

    The gap that matters is a connector-gated project parsed with the wrong `--vars`: the
    manifest is internally consistent and silently partial. Comparing against disk is the
    only signal that catches it.
    """
    model_paths = ["models"]
    project_yml = (project_root / "dbt_project.yml").read_text(encoding="utf-8")
    match = re.search(r'^\s*model-paths:\s*\[([^\]]+)\]', project_yml, re.MULTILINE)
    if match:
        model_paths = re.findall(r'["\']([^"\']+)["\']', match.group(1))

    on_disk: Set[str] = set()
    for mp in model_paths:
        root = project_root / mp
        if root.is_dir():
            on_disk |= {p.stem for p in root.rglob("*.sql")}
    # Local packages carry models too; a coverage gate that cannot see them would call a
    # manifest complete while every extracted connector is missing from it.
    for pkg_models in sorted(project_root.glob("packages/*/models")):
        on_disk |= {p.stem for p in pkg_models.rglob("*.sql")}

    in_manifest = {
        n.get("name")
        for n in man.nodes.values()
        if n.get("resource_type") == "model"
    }
    missing = sorted(on_disk - in_manifest)
    # The opposite direction is a staleness signal, not a gating one: a model in the
    # manifest with no `.sql` behind it was deleted or renamed since the parse. It cannot
    # make the graph partial, but it does put a node in it for a model that no longer
    # exists, so it is reported rather than counted against coverage.
    stale = sorted(in_manifest - on_disk)
    return {
        "on_disk": len(on_disk),
        "in_manifest": len(in_manifest),
        "missing": missing,
        "stale": stale,
        "pct": (len(in_manifest & on_disk) / len(on_disk) * 100) if on_disk else 100.0,
    }


def graphify_python() -> Optional[str]:
    """The interpreter graphify was installed into, as recorded by the skill."""
    marker = REPO / "graphify-out/.graphify_python"
    if marker.exists():
        candidate = marker.read_text(encoding="utf-8").strip()
        if candidate and Path(candidate).exists():
            return candidate
    return None


def merge_into_graph(fragment_path: Path, project_root: Path) -> int:
    """Merge the fragment into graphify-out/graph.json via graphify's own build_merge.

    Shelled out rather than imported: graphify lives in its own uv-managed interpreter, not
    the one running this script.
    """
    python = graphify_python()
    if not python:
        print(
            "graphify interpreter not found (graphify-out/.graphify_python missing).\n"
            f"  Fragment written to {fragment_path}. Run /graphify update to merge it.",
            file=sys.stderr,
        )
        return 3
    code = (
        "import json,sys\n"
        "from pathlib import Path\n"
        "from graphify.build import build_merge\n"
        f"frag=json.loads(Path({str(fragment_path)!r}).read_text(encoding='utf-8'))\n"
        "G=build_merge([frag], graph_path='graphify-out/graph.json', "
        f"root={str(REPO)!r}, directed=False)\n"
        "print(f'merged: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges')\n"
        "out={'nodes':[{'id':n,**d} for n,d in G.nodes(data=True)],\n"
        " 'edges':[{**{k:v for k,v in d.items() if k not in ('_src','_tgt','source','target')},\n"
        "  'source':d.get('_src',u),'target':d.get('_tgt',v)} for u,v,d in G.edges(data=True)],\n"
        " 'hyperedges':list(G.graph.get('hyperedges',[]))}\n"
        "Path('graphify-out/graph.json').write_text(json.dumps(out,ensure_ascii=False),encoding='utf-8')\n"
    )
    result = subprocess.run([python, "-c", code], cwd=REPO, capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
    return result.returncode


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Emit a graphify extraction fragment from a dbt manifest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--manifest", required=True, help="path to manifest.json")
    p.add_argument("--project-root", help="dbt project root (default: inferred)")
    p.add_argument(
        "--out",
        default="graphify-out/.graphify_dbt_extract.json",
        help="where to write the fragment",
    )
    p.add_argument("--merge", action="store_true", help="merge into graphify-out/graph.json")
    p.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    p.add_argument("--no-sources", action="store_true", help="omit source nodes")
    p.add_argument(
        "--with-columns",
        action="store_true",
        help="also emit column nodes and derives_from edges (needs sqlglot; roughly "
             "doubles the graph)",
    )
    p.add_argument(
        "--no-check-coverage",
        action="store_true",
        help="emit even when the manifest covers fewer models than exist on disk",
    )
    p.add_argument(
        "--coverage-threshold",
        type=float,
        default=95.0,
        help="minimum %% of on-disk models the manifest must contain (default: 95)",
    )
    p.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="text for humans; json for machines — pipe through "
             "rust/toon/bin/graph_to_toon for TOON (the PreToolUse hook does it "
             "automatically for agent-run invocations)",
    )
    args = p.parse_args(argv)

    manifest_path = Path(args.manifest)
    man = Manifest.load(str(manifest_path))
    project_root = (
        Path(args.project_root).resolve()
        if args.project_root
        else project_root_of(manifest_path)
    )

    cov = coverage(man, project_root)
    quiet = args.format == "json"

    if quiet:
        # The whole run reported once, as data. Nothing is printed along the way, so the
        # emitted document is the only thing on stdout and stays pipeable into
        # graph_to_toon. Model-name lists are the only uniform records here, and they are
        # what grows without bound on a bad parse.
        blocked = cov["pct"] < args.coverage_threshold and not args.no_check_coverage
        fragment = (
            None if blocked
            else build_fragment(man, project_root, include_sources=not args.no_sources,
                                include_columns=args.with_columns)
        )
        # Lists are capped and paired with a count. A serialization format cannot rescue an
        # unbounded dump: emitting all 332 untested model names costs 10 KB where the count
        # plus a sample costs 200 bytes and answers the same question. TOON is for uniform
        # records you actually need, not for making a dump cheaper.
        payload: Dict[str, Any] = {
            "project": man.project_name,
            "dbt_version": man.dbt_version,
            "adapter": man.adapter_type,
            "models_on_disk": cov["on_disk"],
            "models_in_manifest": cov["in_manifest"],
            "coverage_pct": round(cov["pct"], 1),
            "coverage_blocked": blocked,
            "missing_count": len(cov["missing"]),
            "missing_sample": cov["missing"][:SAMPLE],
            "stale_count": len(cov["stale"]),
            "stale_sample": cov["stale"][:SAMPLE],
        }
        if fragment is not None:
            models = [n for n in fragment["nodes"] if n.get("dbt_resource_type") == "model"]
            payload.update({
                "nodes": len(fragment["nodes"]),
                "models": len(models),
                "sources": sum(
                    1 for n in fragment["nodes"] if n.get("dbt_resource_type") == "source"
                ),
                "macros": sum(
                    1 for n in fragment["nodes"] if n.get("dbt_resource_type") == "macro"
                ),
                "edges": len(fragment["edges"]),
                "hyperedges": len(fragment["hyperedges"]),
                "models_without_tested_key": sum(
                    1 for n in models if not n.get("dbt_pk_tested")
                ),
                "models_without_tested_key_sample": [
                    n["label"] for n in models if not n.get("dbt_pk_tested")
                ][:SAMPLE],
            })
            if not args.dry_run:
                out_path = Path(args.out)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(
                    json.dumps(fragment, ensure_ascii=False), encoding="utf-8"
                )
                payload["wrote"] = str(out_path)
        print(json.dumps(payload, ensure_ascii=False))
        if blocked:
            return 1
        if args.merge and not args.dry_run:
            return merge_into_graph(Path(args.out).resolve(), project_root)
        return 0

    print(f"project:  {man.project_name}  (dbt {man.dbt_version}, {man.adapter_type})")
    print(
        f"coverage: {cov['in_manifest']}/{cov['on_disk']} models "
        f"({cov['pct']:.1f}%) present in the manifest"
    )
    if cov["missing"]:
        shown = ", ".join(cov["missing"][:6])
        more = f" (+{len(cov['missing']) - 6} more)" if len(cov["missing"]) > 6 else ""
        print(f"  missing: {shown}{more}")
    if cov["stale"]:
        shown = ", ".join(cov["stale"][:6])
        more = f" (+{len(cov['stale']) - 6} more)" if len(cov["stale"]) > 6 else ""
        print(
            f"  stale:   {shown}{more}\n"
            f"           in the manifest with no .sql on disk — re-parse before ingesting"
        )

    if cov["pct"] < args.coverage_threshold and not args.no_check_coverage:
        print(
            f"\nERROR: manifest covers {cov['pct']:.1f}% of the models on disk, below the\n"
            f"  {args.coverage_threshold:.0f}% threshold. In a connector-gated project this means the\n"
            f"  parse ran with connectors disabled, and the resulting graph would be silently\n"
            f"  partial. Re-parse with every connector enabled, or pass --no-check-coverage\n"
            f"  if a partial graph is what you want.",
            file=sys.stderr,
        )
        return 1

    fragment = build_fragment(man, project_root, include_sources=not args.no_sources,
                              include_columns=args.with_columns)
    n_models = sum(1 for n in fragment["nodes"] if n.get("dbt_resource_type") == "model")
    n_sources = sum(1 for n in fragment["nodes"] if n.get("dbt_resource_type") == "source")
    untested = [
        n["label"]
        for n in fragment["nodes"]
        if n.get("dbt_resource_type") == "model" and not n.get("dbt_pk_tested")
    ]
    print(
        f"fragment: {len(fragment['nodes'])} nodes "
        f"({n_models} models, {n_sources} sources), "
        f"{len(fragment['edges'])} edges, {len(fragment['hyperedges'])} hyperedges"
    )
    print(f"          {len(untested)}/{n_models} models have no unique+not_null tested key")

    if args.dry_run:
        print("\n(dry run — nothing written)")
        return 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fragment, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out_path}")

    if args.merge:
        return merge_into_graph(out_path.resolve(), project_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
