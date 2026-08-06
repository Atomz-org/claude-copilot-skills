"""Tests for scripts/ontology_mcp_server.py.

The server's whole claim is that it serves `index.json`'s own declaration — the
`mcp_tools` array — without restating it. Three things can silently break that:

1. The generator adds a tool the server has no handler for (or renames one).
   Then `tools/list` and the declaration diverge, and the drift is exactly the
   README-vs-index staleness this server was built to end. Pinned by
   `test_tools_list_matches_the_declaration_exactly`.
2. A handler filters the wrong key, returning plausible records from the wrong
   backing list. Every handler is checked against a direct read of its declared
   `backed_by` key.
3. An unknown concept or column starts reading as an error or — worse — as an
   empty success. Unknown must be an explicit abstention: `found: false`, close
   matches, and for columns the statement that unannotated means UNKNOWN, not
   safe. That last sentence is load-bearing: an agent that reads silence as
   "no PII, additive" produces the exact wrong numbers the annotation store
   exists to prevent.

The tests speak real line-delimited JSON-RPC over a real subprocess pipe — the
same bytes a Claude Code MCP client sends — so framing bugs fail here, not in
the first live session.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "scripts/ontology_mcp_server.py"
INDEX = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics/ontology/index.json"

needs_index = pytest.mark.skipif(not INDEX.exists(), reason="needs the committed index.json")


def _index() -> dict:
    return json.loads(INDEX.read_text(encoding="utf-8"))


def rpc(requests: list[dict], timeout: float = 20.0) -> list[dict]:
    """Run the server, send the standard handshake plus `requests`, return replies."""
    handshake = [
        {"jsonrpc": "2.0", "id": 0, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]
    payload = "".join(json.dumps(m) + "\n" for m in handshake + requests)
    proc = subprocess.run(
        [sys.executable, str(SERVER), "--use-case", "enhanza-analytics"],
        input=payload, capture_output=True, text=True, timeout=timeout, cwd=REPO,
    )
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def call_tool(name: str, arguments: dict) -> dict:
    replies = rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": name, "arguments": arguments}}])
    reply = next(r for r in replies if r.get("id") == 1)
    assert "error" not in reply, reply
    return json.loads(reply["result"]["content"][0]["text"])


# --- the declaration ------------------------------------------------------------------

@needs_index
def test_initialize_names_the_use_case() -> None:
    replies = rpc([])
    init = next(r for r in replies if r.get("id") == 0)
    assert init["result"]["serverInfo"]["use_case"] == "enhanza-analytics"


@needs_index
def test_tools_list_matches_the_declaration_exactly() -> None:
    replies = rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
    listed = next(r for r in replies if r.get("id") == 1)["result"]["tools"]
    served = {t["name"] for t in listed}
    declared = {t["tool"] for t in _index()["mcp_tools"]}
    assert served == declared, (
        f"declared but unserved: {sorted(declared - served)}; "
        f"served but undeclared: {sorted(served - declared)}"
    )
    for tool in listed:
        assert tool["description"], f"{tool['name']} has no description"
        assert "inputSchema" in tool


# --- each handler against its backing key ---------------------------------------------

@needs_index
def test_list_connectors_returns_the_backing_key_verbatim() -> None:
    result = call_tool("list_connectors", {})
    assert result["connectors"] == _index()["connectors"]
    implemented = call_tool("list_connectors", {"status": "implemented"})
    expected = [c for c in _index()["connectors"] if c["status"] == "implemented"]
    assert implemented["connectors"] == expected
    assert implemented["count"] == len(expected)


@needs_index
def test_describe_concept_returns_the_record_and_its_models() -> None:
    concept = _index()["concepts"][0]["concept"]
    result = call_tool("describe_concept", {"concept": concept})
    assert result["found"] is True
    assert result["concept"]["concept"] == concept
    expected_models = [m for m in _index()["models"] if m["concept"] == concept]
    assert result["models"] == expected_models


@needs_index
def test_locate_model_filters_by_connector_and_concept() -> None:
    row = _index()["models"][0]
    result = call_tool("locate_model",
                       {"connector": row["connector"], "concept": row["concept"]})
    assert result["count"] >= 1
    assert all(m["connector"] == row["connector"] and m["concept"] == row["concept"]
               for m in result["models"])


@needs_index
def test_resolve_column_filters_the_mappings() -> None:
    row = _index()["mappings"][0]
    result = call_tool("resolve_column", {"property": row["property"]})
    expected = [m for m in _index()["mappings"] if m["property"] == row["property"]]
    assert result["mappings"] == expected


@needs_index
def test_coverage_gaps_returns_the_backing_key_verbatim() -> None:
    result = call_tool("coverage_gaps", {})
    assert result["gaps"] == _index()["gaps"]


@needs_index
def test_describe_column_returns_the_annotation_record() -> None:
    column = _index()["column_semantics"][0]["column"]
    result = call_tool("describe_column", {"column": column})
    assert result["found"] is True
    assert result["column"] == _index()["column_semantics"][0]


# --- unknown is an abstention, not an error or a silent success -----------------------

@needs_index
def test_unknown_concept_abstains_with_close_matches() -> None:
    result = call_tool("describe_concept", {"concept": "dim_customer"})  # typo: no s
    assert result["found"] is False
    assert "dim_customers" in result["closest"]


@needs_index
def test_unknown_column_states_that_unannotated_is_unknown_not_safe() -> None:
    result = call_tool("describe_column", {"column": "NoSuchColumnAnywhere"})
    assert result["found"] is False
    note = result["note"]
    assert "UNKNOWN" in note
    assert "SUM" in note, "the abstention must warn against assuming summability"


@needs_index
def test_unknown_tool_is_a_jsonrpc_error_not_a_crash() -> None:
    replies = rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "drop_tables", "arguments": {}}}])
    reply = next(r for r in replies if r.get("id") == 1)
    assert reply["error"]["code"] == -32602


# --- unavailable is not failed --------------------------------------------------------

def test_missing_index_exits_3_and_names_the_remedy() -> None:
    proc = subprocess.run(
        [sys.executable, str(SERVER), "--index", "/nonexistent/index.json"],
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 3
    assert "use_case_sync.py" in proc.stderr


# --- the registration -----------------------------------------------------------------

def test_the_repo_registers_the_server() -> None:
    mcp = json.loads((REPO / ".mcp.json").read_text(encoding="utf-8"))
    server = mcp["mcpServers"]["ontology-enhanza-analytics"]
    assert "ontology_mcp_server.py" in " ".join(server["args"])
