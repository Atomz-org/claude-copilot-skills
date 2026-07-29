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
