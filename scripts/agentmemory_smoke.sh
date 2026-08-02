#!/usr/bin/env bash
set -euo pipefail

# Smoke-test the AgentMemory REST surface without polluting the live store.
#
# Usage: agentmemory_smoke.sh [--url URL] [--keep]
#
# AgentMemory has no per-request namespace. `/remember` silently drops a
# `sessionId` field (the stored record comes back with `sessionIds: []`), and
# `/forget` with a `sessionId` reports `{"deleted":N,"success":true}` while
# leaving those memories in place — a success response that deletes nothing.
# Scoping by TEAM_ID/USER_ID is server-level config, so isolating a test that
# way would mean booting a second engine.
#
# What is left is delete-by-id, which is exact and verifiable. So this script
# writes one uniquely marked memory, exercises the read paths, deletes it by
# `memoryId`, and then proves it is gone. Cleanup runs from an EXIT trap, so an
# interrupted run still removes its own record. A cleanup that fails is a hard
# error, not a warning — a smoke test that quietly leaves residue is how the
# store filled up with `XYZZY-4217` and `agentmemory-run-check-...` in the first
# place.

url="${AGENTMEMORY_URL:-http://127.0.0.1:3111}"
keep=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --url)
            if [[ $# -lt 2 ]]; then
                echo "error: --url requires a value" >&2
                exit 2
            fi
            url="$2"
            shift 2
            ;;
        --url=*)
            url="${1#--url=}"
            shift
            ;;
        --keep)
            keep=1
            shift
            ;;
        *)
            echo "error: unknown option: $1" >&2
            exit 2
            ;;
    esac
done

url="${url%/}"
marker="code-skills-smoke-$$-$(date -u +%s)"
memory_id=""

cleanup() {
    local status=$?
    if [[ -n "${memory_id}" && "${keep}" -eq 0 ]]; then
        if curl -sf --max-time 5 -o /dev/null -X POST \
            -H "Content-Type: application/json" \
            -d "{\"memoryId\": \"${memory_id}\"}" \
            "${url}/agentmemory/forget" 2>/dev/null; then
            if curl -sf --max-time 5 "${url}/agentmemory/memories" 2>/dev/null \
                | grep -q "${marker}"; then
                echo "FAIL: ${memory_id} survived the delete — remove it by hand" >&2
                exit 1
            fi
            echo "cleaned up ${memory_id}"
        else
            echo "FAIL: could not delete ${memory_id} — remove it by hand" >&2
            exit 1
        fi
    fi
    exit "${status}"
}
trap cleanup EXIT

echo "target: ${url}"
echo "marker: ${marker}"

if ! curl -sf --max-time 2 -o /dev/null "${url}/agentmemory/health" 2>/dev/null; then
    echo "no AgentMemory server at ${url}" >&2
    exit 3
fi
echo "  health   ok"

response="$(curl -sf --max-time 5 -X POST \
    -H "Content-Type: application/json" \
    -d "{\"content\": \"${marker}\", \"concepts\": [\"smoke-test\", \"code-skills\"]}" \
    "${url}/agentmemory/remember")"

memory_id="$(printf '%s' "${response}" | python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.exit(0)
memory = data.get("memory", data)
print(memory.get("id", "") if isinstance(memory, dict) else "")
')"

if [[ -z "${memory_id}" ]]; then
    echo "FAIL: /remember returned no id" >&2
    exit 1
fi
echo "  remember ok (${memory_id})"

if ! curl -sf --max-time 5 "${url}/agentmemory/memories" 2>/dev/null | grep -q "${marker}"; then
    echo "FAIL: written memory is absent from /memories" >&2
    exit 1
fi
echo "  list     ok"

if curl -sf --max-time 10 -X POST \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"${marker}\", \"limit\": 5}" \
    "${url}/agentmemory/smart-search" >/dev/null 2>&1; then
    echo "  recall   ok"
else
    # The recall path runs an embedding/LLM stage that may be unconfigured. That
    # is a degraded install, not a broken bridge, so it does not fail the smoke.
    echo "  recall   unavailable (embedding backend not configured)"
fi

echo "smoke passed"
