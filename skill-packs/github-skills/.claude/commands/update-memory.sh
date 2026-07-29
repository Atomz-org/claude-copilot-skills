#!/usr/bin/env bash
set -euo pipefail

entry="${1:-update}"
timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
memory_file=".claude/memory.md"
agent_memory_file=".claude/agentmemory.json"
mkdir -p "$(dirname "$agent_memory_file")"

echo "- [$timestamp] $entry" >> "$memory_file"

python3 - "$agent_memory_file" "$entry" "$timestamp" <<'PY'
import json
import os
import sys

path, entry, stamp = sys.argv[1], sys.argv[2], sys.argv[3]
if os.path.exists(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
else:
    data = {"entries": []}

data["entries"].append({"timestamp": stamp, "entry": entry})
with open(path, "w", encoding="utf-8") as handle:
    json.dump(data, handle, indent=2)
    handle.write("\n")
PY

echo "Memory updated in $memory_file and $agent_memory_file"
