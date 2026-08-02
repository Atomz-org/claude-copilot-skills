#!/usr/bin/env bash
set -euo pipefail

entry="${1:-context sync}"
timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
checkpoint_dir=".claude/checkpoints"
checkpoint_file="${checkpoint_dir}/${timestamp//:/-}.json"

mkdir -p "${checkpoint_dir}"

update_memory_cmd=".claude/commands/infra/update-memory.sh"
graph_cmd=".claude/commands/infra/lint-and-graph.sh"

if [[ ! -x "${update_memory_cmd}" ]]; then
    update_memory_cmd=".claude/commands/update-memory.sh"
fi

if [[ ! -x "${graph_cmd}" ]]; then
    graph_cmd=".claude/commands/lint-and-graph.sh"
fi

# Update markdown + json memory logs used by the scaffold.
if [[ -x "${update_memory_cmd}" ]]; then
    "./${update_memory_cmd}" "${entry}"
fi

# Refresh local graph snapshot for quick relationship navigation.
if [[ -x "${graph_cmd}" ]]; then
    "./${graph_cmd}"
fi

python3 - <<'PY' "${entry}" "${timestamp}" "${checkpoint_file}"
import hashlib
import json
import os
import sys

entry = sys.argv[1]
stamp = sys.argv[2]
out_path = sys.argv[3]


def digest(path):
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        h.update(handle.read())
    return h.hexdigest()

payload = {
    "timestamp": stamp,
    "entry": entry,
    "artifacts": {
        "manifest_sha256": digest("target/manifest.json"),
        "run_results_sha256": digest("target/run_results.json"),
        "sources_sha256": digest("target/sources.json"),
        "graph_state_sha256": digest(".claude/graph-state.json"),
    },
}

with open(out_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2)
    handle.write("\n")

print(f"Checkpoint written to {out_path}")
PY

# Mirror the entry to a local AgentMemory server (rohitg00/agentmemory) when one
# is reachable. The committed files above stay the source of truth; this leg is
# best-effort by design, so a checkout or CI runner without the server — or
# without curl — must exit 0 on the exact path it always did.
agentmemory_url="${AGENTMEMORY_URL:-http://127.0.0.1:3111}"
if command -v curl >/dev/null 2>&1 \
    && curl -sf --max-time 1 -o /dev/null "${agentmemory_url}/agentmemory/health" 2>/dev/null; then
    payload="$(python3 - "${entry}" "${checkpoint_file}" <<'PY'
import json
import sys

entry, checkpoint = sys.argv[1], sys.argv[2]
print(json.dumps({
    "content": f"[code-skills context sync] {entry} (checkpoint: {checkpoint})",
    "concepts": ["context-sync", "code-skills"],
}))
PY
)"
    if curl -sf --max-time 3 -o /dev/null -X POST \
        -H "Content-Type: application/json" -d "${payload}" \
        "${agentmemory_url}/agentmemory/remember" 2>/dev/null; then
        echo "Entry mirrored to AgentMemory at ${agentmemory_url}"
    else
        echo "AgentMemory mirror skipped (server refused the write)"
    fi
else
    echo "AgentMemory mirror skipped (no server at ${agentmemory_url})"
fi
