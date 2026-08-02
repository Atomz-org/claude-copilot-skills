"""Pins the read path of AgentMemoryClient.recall() in src/ai-core/memory-store.ts.

/agentmemory/smart-search answers in `mode: "compact"` and has no fuller mode. Every
row is {obsId, score, sessionId, timestamp, title, type}: no `content`, and `title`
truncated to ~79 characters server-side. Ranking without the text is useless to a
caller, so recall() hydrates the hit list from /agentmemory/memories.

Pinned here because the truncation is silent — a regression returns plausible-looking
79-character fragments rather than an error, and a caller reading a fragment of a
decision is worse off than one reading none.

Node is optional: absent Node is unavailable, not failed, so the module is skipped.
"""

import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "src" / "ai-core" / "memory-store.ts"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

FULL = (
    "AgentMemory writes are gated on --decision because commit summaries duplicate "
    "git log and go stale on amend or rebase, and /forget with a sessionId reports "
    "success while deleting nothing."
)
TRUNCATED = FULL[:79]


class _Server(BaseHTTPRequestHandler):
    """Reproduces the real server's compact-search shape."""

    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/agentmemory/memories":
            if self.server.memories_ok:
                self._json({"memories": [
                    {"id": "mem_b", "content": FULL},
                    {"id": "mem_a", "content": "the other memory, in full"},
                ]})
            else:
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/agentmemory/smart-search":
            # Ranked best-first, no content, title truncated — exactly what :3111 sends.
            self._json({"mode": "compact", "lessons": [], "results": [
                {"obsId": "mem_b", "score": 0.9, "sessionId": "memory",
                 "timestamp": "2026-08-02T20:33:12.113Z", "title": TRUNCATED,
                 "type": "decision"},
                {"obsId": "mem_a", "score": 0.1, "sessionId": "memory",
                 "timestamp": "2026-08-02T11:50:31.929Z", "title": "the other memory",
                 "type": "decision"},
            ]})
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def serve(memories_ok=True):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Server)
    server.memories_ok = memories_ok
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def recall_via_node(tmp_path, port, limit=5):
    harness = tmp_path / "harness.ts"
    harness.write_text(
        f"import {{ AgentMemoryClient }} from {json.dumps(str(MODULE))};\n"
        f"const c = new AgentMemoryClient({{ baseUrl: 'http://127.0.0.1:{port}',"
        f" timeoutMs: 5000 }});\n"
        f"console.log(JSON.stringify(await c.recall('anything', {limit})));\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["node", str(harness)], capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_recall_returns_full_content_not_the_truncated_title(tmp_path):
    server = serve()
    try:
        entries = recall_via_node(tmp_path, server.server_address[1])
        assert entries[0]["content"] == FULL
        assert len(entries[0]["content"]) > len(TRUNCATED)
    finally:
        server.shutdown()


def test_recall_preserves_search_ranking(tmp_path):
    server = serve()
    try:
        entries = recall_via_node(tmp_path, server.server_address[1])
        assert [e["id"] for e in entries] == ["mem_b", "mem_a"]
    finally:
        server.shutdown()


def test_recall_honours_the_limit(tmp_path):
    server = serve()
    try:
        assert len(recall_via_node(tmp_path, server.server_address[1], limit=1)) == 1
    finally:
        server.shutdown()


def test_a_failed_hydrate_degrades_to_titles_rather_than_nothing(tmp_path):
    server = serve(memories_ok=False)
    try:
        entries = recall_via_node(tmp_path, server.server_address[1])
        assert len(entries) == 2
        assert entries[0]["content"] == TRUNCATED
    finally:
        server.shutdown()


def test_an_absent_server_recalls_empty_without_throwing(tmp_path):
    assert recall_via_node(tmp_path, 1) == []
