"""Pins for the AgentMemory leg of scripts/sync_context.sh.

The bridge mirrors each context-sync entry to a local AgentMemory server
(rohitg00/agentmemory) when one is reachable. Two properties are load-bearing
and pinned here without needing the real server installed:

- absent server → the script exits 0 on the exact path it always did, and the
  checkpoint is still written (the committed files are the source of truth);
- present server → exactly one JSON POST lands on /agentmemory/remember, with
  the entry text intact even when it contains quotes.
"""

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "sync_context.sh"


def run_sync(tmp_path, entry, url):
    return subprocess.run(
        ["bash", str(SCRIPT), entry],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin",
             "HOME": str(tmp_path), "AGENTMEMORY_URL": url},
        capture_output=True,
        text=True,
        timeout=60,
    )


class _Recorder(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/agentmemory/health" else 404)
        self.end_headers()

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.server.posts.append((self.path, body))
        self.send_response(self.server.post_status)
        self.end_headers()

    def log_message(self, *args):
        pass


def serve(post_status=200):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    server.posts = []
    server.post_status = post_status
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_no_server_still_writes_the_checkpoint_and_exits_zero(tmp_path):
    result = run_sync(tmp_path, "entry without a server", "http://127.0.0.1:1")
    assert result.returncode == 0, result.stderr
    checkpoints = list((tmp_path / ".claude" / "checkpoints").glob("*.json"))
    assert len(checkpoints) == 1
    assert "AgentMemory mirror skipped" in result.stdout


def test_reachable_server_receives_exactly_one_remember_post(tmp_path):
    server = serve()
    try:
        entry = """sync with "quotes" & 'apostrophes'"""
        result = run_sync(tmp_path, entry, f"http://127.0.0.1:{server.server_address[1]}")
        assert result.returncode == 0, result.stderr
        assert "Entry mirrored to AgentMemory" in result.stdout
        assert len(server.posts) == 1
        path, body = server.posts[0]
        assert path == "/agentmemory/remember"
        payload = json.loads(body)
        assert entry in payload["content"]
        assert payload["concepts"] == ["context-sync", "code-skills"]
    finally:
        server.shutdown()


def test_a_refused_write_does_not_fail_the_sync(tmp_path):
    server = serve(post_status=500)
    try:
        result = run_sync(tmp_path, "entry the server rejects",
                          f"http://127.0.0.1:{server.server_address[1]}")
        assert result.returncode == 0, result.stderr
        assert "server refused the write" in result.stdout
        checkpoints = list((tmp_path / ".claude" / "checkpoints").glob("*.json"))
        assert len(checkpoints) == 1
    finally:
        server.shutdown()
