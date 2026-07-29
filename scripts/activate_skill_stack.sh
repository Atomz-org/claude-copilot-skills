#!/usr/bin/env bash
set -euo pipefail

stack="${1:-dbt-skills}"
root="$(cd "$(dirname "$0")/.." && pwd)"
shared_pack="${root}/skill-packs/github-skills/.claude"
domain_pack="${root}/skill-packs/${stack}/.claude"
live_claude="${root}/.claude"

if [[ ! -d "${shared_pack}" ]]; then
  echo "Missing shared pack: ${shared_pack}" >&2
  exit 1
fi

if [[ ! -d "${domain_pack}" ]]; then
  echo "Unknown stack '${stack}'. Available stacks:" >&2
  ls -1 "${root}/skill-packs" >&2
  exit 1
fi

mkdir -p "${live_claude}/commands" "${live_claude}/agents" "${live_claude}/skills" "${live_claude}/rules"

# Keep backward compatibility by layering shared first, then domain.
cp -R "${shared_pack}/commands/." "${live_claude}/commands/"
cp -R "${shared_pack}/agents/." "${live_claude}/agents/"
cp -R "${shared_pack}/rules/." "${live_claude}/rules/"
cp -R "${shared_pack}/skills/." "${live_claude}/skills/"

cp -R "${domain_pack}/commands/." "${live_claude}/commands/"
cp -R "${domain_pack}/agents/." "${live_claude}/agents/"
cp -R "${domain_pack}/rules/." "${live_claude}/rules/"
cp -R "${domain_pack}/skills/." "${live_claude}/skills/"

echo "Activated stack '${stack}' with shared github-skills base."
