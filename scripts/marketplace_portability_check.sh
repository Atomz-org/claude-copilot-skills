#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"

packs=(
  "skill-packs/github-skills"
  "skill-packs/dbt-skills"
  "skill-packs/skill-map"
  "skill-packs/wren-skills"
)

max_bytes=8192
exit_code=0

for pack in "${packs[@]}"; do
  plugin_json="${root}/${pack}/.claude-plugin/plugin.json"
  if [[ ! -f "${plugin_json}" ]]; then
    echo "ERROR: missing plugin manifest: ${pack}/.claude-plugin/plugin.json"
    exit_code=1
  fi

  while IFS= read -r skill_file; do
    bytes=$(wc -c < "${skill_file}" | tr -d ' ')
    if (( bytes > max_bytes )); then
      skill_dir="$(dirname "${skill_file}")"
      if [[ ! -d "${skill_dir}/references" ]]; then
        rel_file="${skill_file#${root}/}"
        echo "ERROR: ${rel_file} is ${bytes} bytes (> ${max_bytes}) and has no references/ directory"
        exit_code=1
      fi
    fi
  done < <(find "${root}/${pack}/.claude/skills" -name SKILL.md -type f)

done

if (( exit_code == 0 )); then
  echo "Marketplace portability checks passed."
fi

exit "${exit_code}"
