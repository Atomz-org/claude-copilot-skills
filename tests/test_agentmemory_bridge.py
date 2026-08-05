"""Pins for the AgentMemory legs of scripts/sync_context.sh and scripts/agentmemory_smoke.sh.

Three properties are load-bearing and pinned here without needing the real
server installed:

- absent server → the sync exits 0 on the exact path it always did, and the
  checkpoint is still written (the committed files are the source of truth);
- a sync carrying `--decision` text POSTs exactly once to /agentmemory/remember,
  with the decision intact even when it contains quotes;
- a sync *without* decision text POSTs nothing at all, even when the server is
  reachable. A commit summary is recoverable from `git log`; mirroring it into a
  memory store adds a stale duplicate and nothing else.

The smoke script is pinned on the property that makes it safe to run against a
live store: whatever it writes, it deletes.
"""

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "sync_context.sh"
SMOKE = REPO / "scripts" / "agentmemory_smoke.sh"

ENV_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"


def run_sync(tmp_path, entry, url, extra_args=(), env_extra=None):
    env = {"PATH": ENV_PATH, "HOME": str(tmp_path), "AGENTMEMORY_URL": url}
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", str(SCRIPT), entry, *extra_args],
        cwd=tmp_path,
        env=env,
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


def url_for(server):
    return f"http://127.0.0.1:{server.server_address[1]}"


def test_no_server_still_writes_the_checkpoint_and_exits_zero(tmp_path):
    result = run_sync(tmp_path, "entry without a server", "http://127.0.0.1:1",
                      ["--decision", "chose X over Y because Z"])
    assert result.returncode == 0, result.stderr
    checkpoints = list((tmp_path / ".claude" / "checkpoints").glob("*.json"))
    assert len(checkpoints) == 1
    assert "no server at" in result.stdout


def test_a_decision_is_mirrored_with_exactly_one_post(tmp_path):
    server = serve()
    try:
        decision = """picked "merge" over delete+insert; 'append' loses late rows"""
        result = run_sync(tmp_path, "feat: incremental strategy", url_for(server),
                          ["--decision", decision])
        assert result.returncode == 0, result.stderr
        assert "Decision mirrored to AgentMemory" in result.stdout
        assert len(server.posts) == 1
        path, body = server.posts[0]
        assert path == "/agentmemory/remember"
        payload = json.loads(body)
        assert payload["content"].startswith(decision)
        assert payload["concepts"] == ["decision", "code-skills"]
    finally:
        server.shutdown()


def test_the_entry_is_provenance_and_never_displaces_the_decision(tmp_path):
    server = serve()
    try:
        result = run_sync(tmp_path, "chore: bump deps", url_for(server),
                          ["--decision", "pinned to 1.4 because 1.5 drops py3.9"])
        assert result.returncode == 0, result.stderr
        payload = json.loads(server.posts[0][1])
        content = payload["content"]
        # The decision leads; the commit summary only trails it as provenance.
        assert content.index("pinned to 1.4") < content.index("chore: bump deps")
        assert "checkpoint" in content
    finally:
        server.shutdown()


def test_without_a_decision_nothing_is_posted_even_when_reachable(tmp_path):
    server = serve()
    try:
        result = run_sync(tmp_path, "feat: some commit summary", url_for(server))
        assert result.returncode == 0, result.stderr
        assert server.posts == []
        assert "no --decision text" in result.stdout
        checkpoints = list((tmp_path / ".claude" / "checkpoints").glob("*.json"))
        assert len(checkpoints) == 1
    finally:
        server.shutdown()


def test_the_decision_can_come_from_the_environment(tmp_path):
    server = serve()
    try:
        result = run_sync(tmp_path, "feat: thing", url_for(server),
                          env_extra={"SYNC_DECISION": "kept the view; the table cost 4x"})
        assert result.returncode == 0, result.stderr
        assert len(server.posts) == 1
        assert "kept the view" in json.loads(server.posts[0][1])["content"]
    finally:
        server.shutdown()


def test_a_refused_write_does_not_fail_the_sync(tmp_path):
    server = serve(post_status=500)
    try:
        result = run_sync(tmp_path, "entry the server rejects", url_for(server),
                          ["--decision", "some rationale"])
        assert result.returncode == 0, result.stderr
        assert "server refused the write" in result.stdout
        checkpoints = list((tmp_path / ".claude" / "checkpoints").glob("*.json"))
        assert len(checkpoints) == 1
    finally:
        server.shutdown()


def test_a_missing_decision_value_is_an_error(tmp_path):
    result = run_sync(tmp_path, "entry", "http://127.0.0.1:1", ["--decision"])
    assert result.returncode == 2
    assert "requires a value" in result.stderr


class _Store(BaseHTTPRequestHandler):
    """Enough of the AgentMemory REST surface to observe the smoke script."""

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/agentmemory/health":
            self.send_response(200)
            self.end_headers()
        elif self.path == "/agentmemory/memories":
            self._json(200, {"memories": list(self.server.store.values())})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/agentmemory/remember":
            self.server.seq += 1
            mem_id = f"mem_stub_{self.server.seq}"
            self.server.store[mem_id] = {"id": mem_id, "content": body.get("content", "")}
            self.server.written.append(mem_id)
            self._json(200, {"memory": self.server.store[mem_id]})
        elif self.path == "/agentmemory/forget":
            mem_id = body.get("memoryId")
            deleted = 1 if self.server.store.pop(mem_id, None) else 0
            self._json(200, {"deleted": deleted, "success": True})
        elif self.path == "/agentmemory/smart-search":
            self._json(200, {"results": []})
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def serve_store():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Store)
    server.store = {}
    server.written = []
    server.seq = 0
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run_smoke(tmp_path, url, extra_args=()):
    return subprocess.run(
        ["bash", str(SMOKE), "--url", url, *extra_args],
        cwd=tmp_path,
        env={"PATH": ENV_PATH, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_smoke_deletes_everything_it_wrote(tmp_path):
    server = serve_store()
    try:
        result = run_smoke(tmp_path, url_for(server))
        assert result.returncode == 0, result.stderr
        assert "smoke passed" in result.stdout
        # It exercised the write path...
        assert len(server.written) == 1
        # ...and left the store exactly as it found it.
        assert server.store == {}
    finally:
        server.shutdown()


def test_smoke_keeps_its_record_only_when_asked(tmp_path):
    server = serve_store()
    try:
        result = run_smoke(tmp_path, url_for(server), ["--keep"])
        assert result.returncode == 0, result.stderr
        assert len(server.store) == 1
    finally:
        server.shutdown()


def test_smoke_reports_an_absent_server_without_failing_hard(tmp_path):
    result = run_smoke(tmp_path, "http://127.0.0.1:1")
    assert result.returncode == 3
    assert "no AgentMemory server" in result.stderr
