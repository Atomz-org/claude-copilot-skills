#!/usr/bin/env bash
set -euo pipefail

# Usage: sync_context.sh [<entry>] [--decision "<why>"]
#
# <entry> labels the checkpoint and the local memory log. It is a terse "what
# happened", and in practice it is the commit summary.
#
# --decision (or the SYNC_DECISION env var) carries the part that is *not*
# recoverable from the repository: why a choice was made, what was ruled out,
# which constraint forced it. Only that text is mirrored to AgentMemory.
#
# Without it the mirror is skipped on purpose. A commit summary in a memory store
# is a duplicate of `git log` — it goes stale the moment the commit is amended or
# rebased, and it crowds out the facts a future session actually needs.

entry=""
decision="${SYNC_DECISION:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --decision)
            if [[ $# -lt 2 ]]; then
                echo "error: --decision requires a value" >&2
                exit 2
            fi
            decision="$2"
            shift 2
            ;;
        --decision=*)
            decision="${1#--decision=}"
            shift
            ;;
        --)
            shift
            ;;
        *)
            if [[ -z "${entry}" ]]; then
                entry="$1"
            fi
            shift
            ;;
    esac
done

entry="${entry:-context sync}"
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

# Mirror the decision to a local AgentMemory server (rohitg00/agentmemory) when
# one is reachable. The committed files above stay the source of truth; this leg
# is best-effort by design, so a checkout or CI runner without the server — or
# without curl — must exit 0 on the exact path it always did.
#
# The decision gate is checked before the health probe: with nothing worth
# remembering there is no reason to touch the network at all.
agentmemory_url="${AGENTMEMORY_URL:-http://127.0.0.1:3111}"
if [[ -z "${decision}" ]]; then
    echo "AgentMemory mirror skipped (no --decision text; checkpoint and local memory still written)"
elif command -v curl >/dev/null 2>&1 \
    && curl -sf --max-time 1 -o /dev/null "${agentmemory_url}/agentmemory/health" 2>/dev/null; then
    payload="$(python3 - "${decision}" "${entry}" "${checkpoint_file}" <<'PY'
import json
import sys

decision, entry, checkpoint = sys.argv[1], sys.argv[2], sys.argv[3]
# The decision leads; provenance trails it so a reader can find the change it
# belongs to without the summary displacing the reasoning.
print(json.dumps({
    "content": f"{decision}\n\n(code-skills — {entry}; checkpoint {checkpoint})",
    "concepts": ["decision", "code-skills"],
}))
PY
)"
    if curl -sf --max-time 3 -o /dev/null -X POST \
        -H "Content-Type: application/json" -d "${payload}" \
        "${agentmemory_url}/agentmemory/remember" 2>/dev/null; then
        echo "Decision mirrored to AgentMemory at ${agentmemory_url}"
    else
        echo "AgentMemory mirror skipped (server refused the write)"
    fi
else
    echo "AgentMemory mirror skipped (no server at ${agentmemory_url})"
fi
