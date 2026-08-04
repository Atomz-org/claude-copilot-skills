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

mkdir -p "${live_claude}/commands" "${live_claude}/agents" "${live_claude}/skills" "${live_claude}/rules" "${live_claude}/hooks"

# A pack is not required to carry every component. skill-map, for instance,
# ships skills/commands/rules and no agents/ — and an unconditional `cp -R` on a
# missing directory aborts the whole activation under `set -e`, leaving .claude/
# half-layered. Copy what exists and skip the rest.
copy_component() {
  local src="$1" dest="$2"
  [[ -d "${src}" ]] && cp -R "${src}/." "${dest}/"
  return 0
}

# Keep backward compatibility by layering shared first, then domain.
for component in commands agents rules skills hooks; do
  copy_component "${shared_pack}/${component}" "${live_claude}/${component}"
done

for component in commands agents rules skills; do
  copy_component "${domain_pack}/${component}" "${live_claude}/${component}"
done

# Reference docs and artifact templates ship at the pack root, not under .claude/. Skills,
# agents, and commands link to them as ../../references/<file>.md and ../../templates/<file>.md
# (one level deeper from skills/). Those paths resolve to the pack root while the file lives
# in the pack, and to the repository root once the pack is activated. Materialising both
# directories here keeps a single relative link valid in both locations.
for pack in "${shared_pack%/.claude}" "${domain_pack%/.claude}"; do
  for asset in references templates; do
    if [[ -d "${pack}/${asset}" ]]; then
      mkdir -p "${root}/${asset}"
      cp -R "${pack}/${asset}/." "${root}/${asset}/"
    fi
  done
done

if [[ -f "${live_claude}/hooks/block-dangerous-git.sh" ]]; then
  chmod +x "${live_claude}/hooks/block-dangerous-git.sh"
fi

# Merge drivers are per-clone git config; .gitattributes names them but cannot
# register them. Activation is the one path every working clone passes through,
# so registering here keeps the conflict-resolution behavior uniform without a
# separate setup step. Quiet: config lands in .git/, invisible to the
# activation-drift gate.
if [[ -x "${root}/scripts/setup_git_merge_drivers.sh" ]]; then
  "${root}/scripts/setup_git_merge_drivers.sh" >/dev/null
fi

echo "Activated stack '${stack}' with shared github-skills base."
