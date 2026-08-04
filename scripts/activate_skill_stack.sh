#!/usr/bin/env bash
set -euo pipefail

# One or more domain stacks, layered in argument order over the shared base.
# `activate_skill_stack.sh dbt-skills wren-skills` composes the analytics stack with the
# WrenAI serving tier; a single argument behaves exactly as before. Later stacks win on
# a filename collision — `scripts/skill_map_scan.py --check` is the gate that reports one.
# The no-arg default is the SAME stack list CI activates, so the documented bare
# invocation and the CI drift gate can never diverge.
stacks=("$@")
if [[ ${#stacks[@]} -eq 0 ]]; then
  stacks=("dbt-skills" "wren-skills")
fi
root="$(cd "$(dirname "$0")/.." && pwd)"
shared_pack="${root}/skill-packs/github-skills/.claude"
live_claude="${root}/.claude"

if [[ ! -d "${shared_pack}" ]]; then
  echo "Missing shared pack: ${shared_pack}" >&2
  exit 1
fi

for stack in "${stacks[@]}"; do
  if [[ ! -d "${root}/skill-packs/${stack}/.claude" ]]; then
    echo "Unknown stack '${stack}'. Available stacks:" >&2
    ls -1 "${root}/skill-packs" >&2
    exit 1
  fi
done

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

# Keep backward compatibility by layering shared first, then each domain stack in order.
for component in commands agents rules skills hooks; do
  copy_component "${shared_pack}/${component}" "${live_claude}/${component}"
done

for stack in "${stacks[@]}"; do
  for component in commands agents rules skills; do
    copy_component "${root}/skill-packs/${stack}/.claude/${component}" "${live_claude}/${component}"
  done
done

# Reference docs and artifact templates ship at the pack root, not under .claude/. Skills,
# agents, and commands link to them as ../../references/<file>.md and ../../templates/<file>.md
# (one level deeper from skills/). Those paths resolve to the pack root while the file lives
# in the pack, and to the repository root once the pack is activated. Materialising both
# directories here keeps a single relative link valid in both locations.
asset_packs=("${shared_pack%/.claude}")
for stack in "${stacks[@]}"; do
  asset_packs+=("${root}/skill-packs/${stack}")
done
for pack in "${asset_packs[@]}"; do
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

echo "Activated stack(s) '${stacks[*]}' with shared github-skills base."
