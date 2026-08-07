#!/usr/bin/env python3
"""MCP server over a use-case's ontology/index.json — the six declared tools, served.

`index.json` has always *declared* its MCP surface: an `mcp_tools` array naming each
tool, the key that backs it, and the question it answers. Until this file, nothing
served it — the declaration was a projection with no consumer, and an agent wanting
`describe_column` re-ran Python scripts or read a 133 KB JSON file into context.

Design rules, in the order they bit:

- **The tool list is derived from the file, never restated.** `tools/list` is built
  by walking `index.json`'s own `mcp_tools` — name and description come from the
  artifact, so the generator (`scripts/ontology_generator.py`, `MCP_TOOLS`) and this
  server cannot disagree about what exists. A declared tool this server has no
  handler for is reported on stderr at startup and *omitted* from `tools/list`;
  advertising a tool that errors on call is worse than not advertising it.
  `tests/test_ontology_mcp_server.py` pins the two lists equal, so drift fails CI
  rather than surfacing as a runtime hole.
- **Read once, serve many.** The index is loaded at startup. It is a committed
  artifact that changes only when the ontology is regenerated; a server watching it
  for changes would add a failure mode to save a restart nobody minds.
- **Absent is not an error, and unknown is not safe.** `describe_concept` on a name
  the ontology never declared returns `found: false` plus the closest declared names
  — an agent that typoed `dim_customer` needs `dim_customers`, not a stack trace.
  `describe_column` on an unannotated column additionally says, in words, that
  unannotated additivity and PII are UNKNOWN — the annotation store abstains rather
  than guesses (rule 5), and this server carries the abstention through rather than
  letting silence read as "safe to SUM".
- **Stdlib only.** Same rule as every script in scripts/: the server must start on
  any machine that has Python, because the machines that need it most (fresh clones,
  CI) are the ones with nothing installed. MCP's stdio transport is line-delimited
  JSON-RPC 2.0, which the stdlib covers.

Registration (repo root `.mcp.json`):

    {"mcpServers": {"ontology-enhanza-analytics": {
        "command": "python3",
        "args": ["scripts/ontology_mcp_server.py", "--use-case", "enhanza-analytics"]}}}

Regenerate the index it serves:  python3 scripts/use_case_sync.py --use-case <slug>
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import require_use_case_dir  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "ontology-index"
SERVER_VERSION = "1.0.0"

# Parameter schemas cannot live in index.json (it declares tools, not signatures),
# so they live here, keyed by tool name. A tool with no entry here is declared but
# unservable — reported at startup, excluded from tools/list.
TOOL_INPUT_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "list_connectors": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["implemented", "planned"],
                       "description": "Only connectors with this status."},
            "kind": {"type": "string", "enum": ["erp", "crm", "commerce"],
                     "description": "Only connectors of this kind."},
        },
    },
    "describe_concept": {
        "type": "object",
        "properties": {
            "concept": {"type": "string",
                        "description": "Conformed concept name, e.g. dim_customers."},
        },
        "required": ["concept"],
    },
    "locate_model": {
        "type": "object",
        "properties": {
            "connector": {"type": "string", "description": "Connector key, e.g. fortnox."},
            "concept": {"type": "string", "description": "Conformed concept name."},
        },
    },
    "resolve_column": {
        "type": "object",
        "properties": {
            "property": {"type": "string",
                         "description": "Conformed property, e.g. erp:currency."},
            "connector": {"type": "string", "description": "Restrict to one connector."},
            "concept": {"type": "string", "description": "Restrict to one concept."},
        },
    },
    "coverage_gaps": {"type": "object", "properties": {}},
    "describe_column": {
        "type": "object",
        "properties": {
            "column": {"type": "string",
                       "description": "Conformed column name, e.g. TotalToPay."},
        },
        "required": ["column"],
    },
}


def _close_matches(name: str, candidates: List[str]) -> List[str]:
    return difflib.get_close_matches(name, candidates, n=5, cutoff=0.5)


class OntologyIndex:
    """The six tool handlers, each a thin filter over one backing key."""

    def __init__(self, index: Dict[str, Any]):
        self.index = index

    # -- handlers ----------------------------------------------------------------

    def list_connectors(self, status: Optional[str] = None,
                        kind: Optional[str] = None) -> Dict[str, Any]:
        rows = self.index.get("connectors", [])
        if status:
            rows = [r for r in rows if r.get("status") == status]
        if kind:
            rows = [r for r in rows if r.get("kind") == kind]
        return {"connectors": rows, "count": len(rows)}

    def describe_concept(self, concept: str) -> Dict[str, Any]:
        for row in self.index.get("concepts", []):
            if row.get("concept") == concept:
                models = [m for m in self.index.get("models", [])
                          if m.get("concept") == concept]
                return {"found": True, "concept": row, "models": models}
        names = [r.get("concept", "") for r in self.index.get("concepts", [])]
        return {"found": False, "concept": concept,
                "closest": _close_matches(concept, names),
                "note": "not a declared concept in this ontology"}

    def locate_model(self, connector: Optional[str] = None,
                     concept: Optional[str] = None) -> Dict[str, Any]:
        rows = self.index.get("models", [])
        if connector:
            rows = [r for r in rows if r.get("connector") == connector]
        if concept:
            rows = [r for r in rows if r.get("concept") == concept]
        return {"models": rows, "count": len(rows)}

    def resolve_column(self, property: Optional[str] = None,
                       connector: Optional[str] = None,
                       concept: Optional[str] = None) -> Dict[str, Any]:
        rows = self.index.get("mappings", [])
        if property:
            rows = [r for r in rows if r.get("property") == property]
        if connector:
            rows = [r for r in rows if r.get("connector") == connector]
        if concept:
            rows = [r for r in rows if r.get("concept") == concept]
        return {"mappings": rows, "count": len(rows)}

    def coverage_gaps(self) -> Dict[str, Any]:
        rows = self.index.get("gaps", [])
        return {"gaps": rows, "count": len(rows)}

    def describe_column(self, column: str) -> Dict[str, Any]:
        for row in self.index.get("column_semantics", []):
            if row.get("column") == column:
                return {"found": True, "column": row}
        names = [r.get("column", "") for r in self.index.get("column_semantics", [])]
        return {
            "found": False,
            "column": column,
            "closest": _close_matches(column, names),
            "note": ("no annotation for this column: its additivity and PII class are "
                     "UNKNOWN, not none — do not assume SUM() is meaningful or that it "
                     "is safe to expose. The annotation store abstains rather than "
                     "guesses; see scripts/column_annotations.py --coverage."),
        }

    # -- MCP wiring --------------------------------------------------------------

    def declared_tools(self) -> List[Dict[str, str]]:
        return list(self.index.get("mcp_tools", []))

    def servable_tools(self) -> List[Dict[str, Any]]:
        """tools/list payload: names and descriptions from the artifact, schemas here."""
        tools = []
        for entry in self.declared_tools():
            name = entry.get("tool", "")
            if name not in TOOL_INPUT_SCHEMAS or not hasattr(self, name):
                print(f"warning: index.json declares tool {name!r} this server "
                      f"cannot serve — regenerate or update the server", file=sys.stderr)
                continue
            tools.append({
                "name": name,
                "description": f"{entry.get('answers', '')} (backed by "
                               f"index.json[{entry.get('backed_by', '?')}])",
                "inputSchema": TOOL_INPUT_SCHEMAS[name],
            })
        return tools

    def call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if name not in TOOL_INPUT_SCHEMAS or not hasattr(self, name):
            raise ValueError(f"unknown tool: {name}")
        return getattr(self, name)(**arguments)


def serve(index_path: Path) -> int:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    ontology = OntologyIndex(index)

    def reply(msg_id: Any, result: Dict[str, Any]) -> None:
        _write({"jsonrpc": "2.0", "id": msg_id, "result": result})

    def reply_error(msg_id: Any, code: int, message: str) -> None:
        _write({"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": code, "message": message}})

    def _write(obj: Dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method", "")
        msg_id = msg.get("id")
        if method == "initialize":
            reply(msg_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION,
                               "use_case": index.get("use_case", "?")},
            })
        elif method == "notifications/initialized":
            continue  # notification: no reply
        elif method == "tools/list":
            reply(msg_id, {"tools": ontology.servable_tools()})
        elif method == "tools/call":
            params = msg.get("params", {})
            try:
                result = ontology.call(params.get("name", ""),
                                       params.get("arguments", {}) or {})
                reply(msg_id, {"content": [
                    {"type": "text", "text": json.dumps(result, ensure_ascii=False)}
                ]})
            except (ValueError, TypeError) as exc:
                reply_error(msg_id, -32602, str(exc))
        elif msg_id is not None:
            reply_error(msg_id, -32601, f"method not found: {method}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--use-case", default="enhanza-analytics",
                        help="use-case slug whose ontology/index.json to serve")
    parser.add_argument("--index", type=Path, default=None,
                        help="explicit index.json path (overrides --use-case)")
    args = parser.parse_args()

    if args.index is not None:
        index_path = args.index
    else:
        index_path = require_use_case_dir(args.use_case) / "ontology" / "index.json"

    if not index_path.exists():
        print(f"no index at {index_path} — generate it first:\n"
              f"  python3 scripts/use_case_sync.py --use-case {args.use_case}",
              file=sys.stderr)
        return 3  # unavailable is not failed: named remedy, distinct exit code

    return serve(index_path)


if __name__ == "__main__":
    raise SystemExit(main())
