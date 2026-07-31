"""Shared manifest helpers for the dbt Core analytics-engineering scripts.

Runs on the standard library alone. Every script here reads dbt's JSON artifacts; none
connect to a warehouse. Run any dbt command (`dbt parse` is enough) to produce
`target/manifest.json`.

JSON parsing prefers `orjson` when it happens to be importable and falls back to the
standard library otherwise — the same shape as `_miniyaml.load`, which prefers PyYAML.
The example artifacts in this repository parse in well under a millisecond, so the
accelerator is pointless at that size; a production `manifest.json` runs to hundreds of
megabytes, where the parse stops being free. Either way the install stays optional,
which is the whole point of a no-install-step scaffold.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

try:  # optional accelerator — absence is the normal case, not an error
    import orjson as _orjson
except ImportError:  # pragma: no cover - depends on the environment
    _orjson = None  # type: ignore[assignment]

# ---------------------------------------------------------------- loading


def using_orjson() -> bool:
    """True when the optional orjson accelerator is parsing artifacts."""
    return _orjson is not None


def json_parser_name() -> str:
    """Human-readable name of the active JSON parser, for `--verbose` output."""
    return "orjson" if using_orjson() else "bundled standard-library json"


def loads(raw: bytes) -> Any:
    """Parse UTF-8 JSON bytes with orjson when available, else the standard library.

    Bytes rather than str on purpose: both parsers decode UTF-8 internally, so handing
    them the raw bytes skips a separate decode pass over the whole artifact. Both raise
    a `ValueError` subclass on malformed input, so callers catch one exception type.
    """
    if _orjson is not None:
        return _orjson.loads(raw)
    return json.loads(raw)


def load_json(path: str, what: str = "artifact") -> Dict[str, Any]:
    """Load a dbt artifact, failing with an actionable message."""
    if not os.path.exists(path):
        die(
            f"{what} not found: {path}\n"
            f"  Run a dbt command first — `dbt parse` writes manifest.json without\n"
            f"  touching the warehouse. `dbt build` writes run_results.json,\n"
            f"  `dbt source freshness` writes sources.json, `dbt docs generate`\n"
            f"  writes catalog.json."
        )
    try:
        with open(path, "rb") as fh:
            return loads(fh.read())
    except ValueError as exc:  # json.JSONDecodeError and orjson.JSONDecodeError both
        die(f"{what} at {path} is not valid JSON: {exc}")
    return {}  # unreachable; keeps type checkers quiet


def die(message: str, code: int = 2) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- manifest access


class Manifest:
    """Thin, defensive wrapper over manifest.json.

    dbt's manifest schema shifts between minor versions, so everything here uses
    .get() with sane defaults rather than assuming keys exist.
    """

    def __init__(self, data: Dict[str, Any], path: str = "") -> None:
        self.data = data
        self.path = path
        self.nodes: Dict[str, Any] = data.get("nodes", {}) or {}
        self.sources: Dict[str, Any] = data.get("sources", {}) or {}
        self.exposures: Dict[str, Any] = data.get("exposures", {}) or {}
        self.metrics: Dict[str, Any] = data.get("metrics", {}) or {}
        self.semantic_models: Dict[str, Any] = data.get("semantic_models", {}) or {}
        self.saved_queries: Dict[str, Any] = data.get("saved_queries", {}) or {}
        self.macros: Dict[str, Any] = data.get("macros", {}) or {}
        self.metadata: Dict[str, Any] = data.get("metadata", {}) or {}
        self._child_map: Optional[Dict[str, List[str]]] = data.get("child_map")
        self._parent_map: Optional[Dict[str, List[str]]] = data.get("parent_map")

    # -- basics ----------------------------------------------------

    @classmethod
    def load(cls, path: str) -> "Manifest":
        return cls(load_json(path, "manifest.json"), path)

    @property
    def dbt_version(self) -> str:
        return self.metadata.get("dbt_version", "unknown")

    @property
    def project_name(self) -> str:
        return self.metadata.get("project_name", "unknown")

    @property
    def adapter_type(self) -> str:
        return self.metadata.get("adapter_type", "unknown")

    def all_nodes(self) -> Dict[str, Any]:
        """Every addressable node: models, tests, snapshots, seeds, sources, exposures."""
        merged: Dict[str, Any] = {}
        merged.update(self.nodes)
        merged.update(self.sources)
        merged.update(self.exposures)
        return merged

    # -- selection -------------------------------------------------

    def models(self) -> Dict[str, Any]:
        return {
            uid: n
            for uid, n in self.nodes.items()
            if n.get("resource_type") == "model"
        }

    def tests(self) -> Dict[str, Any]:
        return {
            uid: n
            for uid, n in self.nodes.items()
            if n.get("resource_type") in ("test", "unit_test")
        }

    def unit_tests(self) -> Dict[str, Any]:
        # dbt places unit tests in `unit_tests` (1.8+) or inline in `nodes`.
        inline = {
            uid: n
            for uid, n in self.nodes.items()
            if n.get("resource_type") == "unit_test"
        }
        top = self.data.get("unit_tests", {}) or {}
        merged = dict(inline)
        merged.update(top)
        return merged

    def snapshots(self) -> Dict[str, Any]:
        return {
            uid: n
            for uid, n in self.nodes.items()
            if n.get("resource_type") == "snapshot"
        }

    def seeds(self) -> Dict[str, Any]:
        return {
            uid: n for uid, n in self.nodes.items() if n.get("resource_type") == "seed"
        }

    def find_model(self, name: str) -> Tuple[str, Dict[str, Any]]:
        """Resolve a model by name or unique_id. Exits with suggestions if ambiguous."""
        if name in self.nodes:
            return name, self.nodes[name]
        matches = [
            (uid, n) for uid, n in self.models().items() if n.get("name") == name
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            close = sorted(
                n.get("name", "")
                for n in self.models().values()
                if name.lower() in str(n.get("name", "")).lower()
            )[:8]
            hint = f"\n  Did you mean: {', '.join(close)}" if close else ""
            die(f"model '{name}' not found in {self.path}{hint}")
        die(
            f"'{name}' is ambiguous — matches {len(matches)} nodes. "
            f"Pass a unique_id instead: {', '.join(m[0] for m in matches[:5])}"
        )
        return "", {}  # unreachable

    # -- graph -----------------------------------------------------

    def child_map(self) -> Dict[str, List[str]]:
        if self._child_map is not None:
            return self._child_map
        # Older manifests may omit child_map; rebuild it from depends_on.
        built: Dict[str, List[str]] = {uid: [] for uid in self.all_nodes()}
        for uid, node in self.nodes.items():
            for parent in node.get("depends_on", {}).get("nodes", []) or []:
                built.setdefault(parent, []).append(uid)
        for uid, exposure in self.exposures.items():
            for parent in exposure.get("depends_on", {}).get("nodes", []) or []:
                built.setdefault(parent, []).append(uid)
        self._child_map = built
        return built

    def parent_map(self) -> Dict[str, List[str]]:
        if self._parent_map is not None:
            return self._parent_map
        built: Dict[str, List[str]] = {}
        for uid, node in self.nodes.items():
            built[uid] = list(node.get("depends_on", {}).get("nodes", []) or [])
        for uid, exposure in self.exposures.items():
            built[uid] = list(exposure.get("depends_on", {}).get("nodes", []) or [])
        self._parent_map = built
        return built

    def descendants(self, uid: str, max_depth: int = 999) -> Set[str]:
        return self._walk(uid, self.child_map(), max_depth)

    def ancestors(self, uid: str, max_depth: int = 999) -> Set[str]:
        return self._walk(uid, self.parent_map(), max_depth)

    @staticmethod
    def _walk(start: str, adjacency: Dict[str, List[str]], max_depth: int) -> Set[str]:
        seen: Set[str] = set()
        frontier = [start]
        depth = 0
        while frontier and depth < max_depth:
            nxt: List[str] = []
            for uid in frontier:
                for neighbour in adjacency.get(uid, []) or []:
                    if neighbour not in seen and neighbour != start:
                        seen.add(neighbour)
                        nxt.append(neighbour)
            frontier = nxt
            depth += 1
        return seen

    def find_cycles(self) -> List[List[str]]:
        """Return cycles among model/snapshot nodes (dbt normally prevents these,
        but a manifest hand-assembled or mid-refactor can contain one)."""
        parents = self.parent_map()
        colour: Dict[str, int] = {}
        cycles: List[List[str]] = []
        stack: List[str] = []

        def visit(uid: str) -> None:
            colour[uid] = 1
            stack.append(uid)
            for parent in parents.get(uid, []) or []:
                if parent not in self.nodes:
                    continue
                state = colour.get(parent, 0)
                if state == 0:
                    visit(parent)
                elif state == 1 and parent in stack:
                    cycles.append(stack[stack.index(parent):] + [parent])
            stack.pop()
            colour[uid] = 2

        sys.setrecursionlimit(max(10000, len(self.nodes) * 4))
        for uid in self.nodes:
            if colour.get(uid, 0) == 0:
                visit(uid)
        return cycles

    # -- test attachment -------------------------------------------

    def tests_by_model(self) -> Dict[str, List[Dict[str, Any]]]:
        """Map model unique_id -> the test nodes attached to it."""
        out: Dict[str, List[Dict[str, Any]]] = {uid: [] for uid in self.models()}
        for uid, node in self.nodes.items():
            if node.get("resource_type") not in ("test", "unit_test"):
                continue
            attached = node.get("attached_node")
            targets = (
                [attached]
                if attached
                else (node.get("depends_on", {}).get("nodes", []) or [])
            )
            for target in targets:
                if target in out:
                    out[target].append(node)
        # Unit tests may live in `nodes` (already handled above) or in a top-level
        # `unit_tests` key depending on the dbt version. Track what we have added so a
        # manifest carrying both does not double-count.
        seen = {
            t.get("unique_id")
            for tests in out.values()
            for t in tests
            if t.get("unique_id")
        }
        for uid, node in self.unit_tests().items():
            if node.get("unique_id", uid) in seen:
                continue
            target_name = node.get("model")
            for muid, model in self.models().items():
                if model.get("name") == target_name:
                    out.setdefault(muid, []).append(
                        {**node, "resource_type": "unit_test"}
                    )
                    seen.add(node.get("unique_id", uid))
                    break
        return out


# ---------------------------------------------------------------- node helpers


def layer_of(node: Dict[str, Any]) -> str:
    """Infer the layer from the node's path. Falls back on the name prefix."""
    path = (node.get("path") or node.get("original_file_path") or "").replace("\\", "/")
    lowered = path.lower()
    for candidate in ("staging", "intermediate", "marts", "mart", "semantic", "utilities"):
        if f"/{candidate}/" in f"/{lowered}" or lowered.startswith(candidate + "/"):
            return "marts" if candidate == "mart" else candidate
    name = (node.get("name") or "").lower()
    if name.startswith("stg_"):
        return "staging"
    if name.startswith("int_"):
        return "intermediate"
    if name.startswith(("fct_", "dim_", "rpt_", "agg_", "bridge_")):
        return "marts"
    return "other"


def test_names_for(tests: Iterable[Dict[str, Any]]) -> Set[str]:
    """Generic test names attached to a node (e.g. {'unique','not_null'})."""
    names: Set[str] = set()
    for test in tests:
        meta = test.get("test_metadata") or {}
        if meta.get("name"):
            names.add(str(meta["name"]))
        elif test.get("resource_type") == "unit_test":
            names.add("__unit_test__")
        else:
            names.add("__singular__")
    return names


def collect_tested_columns(tests: Iterable[Dict[str, Any]]) -> Dict[str, Set[str]]:
    """Map column name -> set of generic test names applied to it."""
    out: Dict[str, Set[str]] = {}
    for test in tests:
        meta = test.get("test_metadata") or {}
        column = test.get("column_name") or (meta.get("kwargs") or {}).get("column_name")
        if not column:
            continue
        out.setdefault(str(column), set()).add(str(meta.get("name", "unknown")))
    return out


def has_primary_key_tests(tests: Iterable[Dict[str, Any]]) -> bool:
    """True when some single column carries both `unique` and `not_null`, or when a
    composite-grain test (unique_combination_of_columns) is present."""
    tests = list(tests)
    by_column = collect_tested_columns(tests)
    for names in by_column.values():
        if "unique" in names and "not_null" in names:
            return True
    for test in tests:
        name = ((test.get("test_metadata") or {}).get("name") or "").lower()
        if "unique_combination_of_columns" in name:
            return True
    return False


# ---------------------------------------------------------------- output


class Colors:
    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    BLUE = "\033[94m"
    GREY = "\033[90m"
    BOLD = "\033[1m"
    END = "\033[0m"

    @classmethod
    def disable(cls) -> None:
        for attr in ("RED", "YELLOW", "GREEN", "BLUE", "GREY", "BOLD", "END"):
            setattr(cls, attr, "")


if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    Colors.disable()


def header(text: str) -> None:
    print(f"\n{Colors.BOLD}{text}{Colors.END}")
    print("=" * min(len(text), 78))


def section(text: str) -> None:
    print(f"\n{Colors.BOLD}{text}{Colors.END}")
    print("-" * min(len(text), 78))


def severity_tag(severity: str) -> str:
    return {
        "error": f"{Colors.RED}ERROR{Colors.END}",
        "warn": f"{Colors.YELLOW}WARN {Colors.END}",
        "info": f"{Colors.BLUE}INFO {Colors.END}",
    }.get(severity, severity.upper())


def table(rows: List[List[str]], headers: List[str], max_width: int = 60) -> None:
    """Print a simple aligned text table."""
    if not rows:
        print("  (none)")
        return
    cols = len(headers)
    trimmed = [
        [str(cell)[:max_width] for cell in (row + [""] * cols)[:cols]] for row in rows
    ]
    widths = [
        max(len(headers[i]), max((len(r[i]) for r in trimmed), default=0))
        for i in range(cols)
    ]
    print("  " + "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  " + "  ".join("-" * widths[i] for i in range(cols)))
    for row in trimmed:
        print("  " + "  ".join(row[i].ljust(widths[i]) for i in range(cols)))


def fmt_seconds(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"
