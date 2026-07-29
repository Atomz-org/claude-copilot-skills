#!/usr/bin/env bash
set -euo pipefail

echo "Running repository checks..."
if command -v ruff >/dev/null 2>&1; then
  ruff check .
elif command -v eslint >/dev/null 2>&1; then
  eslint .
else
  echo "No linter detected; continuing with scaffold checks."
fi

python3 - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path

root = Path('.')
entries = []
for path in sorted(root.rglob('*')):
    if any(part in {'.git', '.venv', 'node_modules'} for part in path.parts):
        continue
    if path.is_file() and path.suffix in {'.py', '.ts', '.md', '.sh', '.yml', '.yaml', '.json'}:
        entries.append(str(path))

output = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "nodes": entries,
    "edges": []
}
Path('.claude').mkdir(exist_ok=True)
with open('.claude/graph-state.json', 'w', encoding='utf-8') as handle:
    json.dump(output, handle, indent=2)
    handle.write('\n')
PY

echo "Graph snapshot written to .claude/graph-state.json"
